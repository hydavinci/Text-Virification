# mypy: ignore-errors
# ruff: noqa
"""
原文检查分析引擎
支持中文和英文文本的错误检测，包括错别字、标点、语法、格式等问题。
"""

import re
import json
import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple


@dataclass
class Issue:
    """单个问题的数据结构"""
    type: str          # typo, variant_char, width_mixed, missing_char, idiom_misuse,
                       # expression, grammar, logic, punctuation, spacing, number_format,
                       # repetition, style, colloquial
    severity: str      # error, warning, info
    original: str      # 问题文本
    suggestion: str    # 修改建议
    position: int      # 起始位置
    end_position: int  # 结束位置
    context: str       # 上下文
    description: str   # 问题说明
    rule_id: str       # 规则ID
    alternatives: Optional[List[str]] = None  # 改写候选方案（用户可选择）
    layer: str = ''    # 检查层级：character/vocabulary/sentence/format/discourse/security
    review: str = ''   # 云端语义复核结论：false_positive/real/uncertain/no_verdict
    review_reason: str = ''  # 复核理由

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 六层检查体系：type → layer 映射
# ============================================================
TYPE_TO_LAYER = {
    # 字符层
    'typo': 'character',
    'variant_char': 'character',
    'width_mixed': 'character',
    # 词汇层
    'missing_char': 'vocabulary',
    'idiom_misuse': 'vocabulary',
    'custom_term': 'vocabulary',
    'term_consistency': 'vocabulary',
    # 句子层
    'expression': 'sentence',
    'grammar': 'sentence',
    'logic': 'sentence',
    # 标点/格式层
    'punctuation': 'format',
    'spacing': 'format',
    'number_format': 'format',
    # 语篇/语体层
    'repetition': 'discourse',
    'style': 'discourse',
    'colloquial': 'discourse',
    'banned_word': 'discourse',
    # 合规/安全层
    'pii_id': 'security', 'pii_phone': 'security', 'pii_email': 'security',
    'pii_bank': 'security', 'pii_key': 'security',
    # 敏感内容（涉政 / 民族宗教 / 领土规范表述）：统一归入合规/安全层
    'sensitive_politics': 'security',
    'sensitive_ethnic_religion': 'security',
    'sensitive_territory': 'security',
    # 广告法极限词（绝对化用语）：营销合规，统一归入合规/安全层
    'ad_extreme': 'security',
}

LAYER_NAMES = {
    'character': '字符层',
    'vocabulary': '词汇层',
    'sentence': '句子层',
    'format': '标点/格式层',
    'discourse': '语篇/语体层',
    'security': '合规/安全层',
}

# ============================================================
# 敏感内容（涉政 / 民族宗教 / 领土规范表述）词典：服务端加载
# 词表内容由合规/法务团队审定维护，工程仅做引擎，前端不暴露。
# 按文件修改时间热加载，合规修改词表后无需重启即生效。
# ============================================================
_SENSITIVE_RULES_CACHE = {'path': None, 'mtime': 0, 'data': {}}

def _load_sensitive_rules() -> Dict:
    """加载服务端敏感内容词典；带 mtime 缓存，词表更新后自动热加载。"""
    path = Path(__file__).with_name('data') / 'sensitive_rules.json'
    try:
        mtime = path.stat().st_mtime
        if _SENSITIVE_RULES_CACHE['path'] == path and _SENSITIVE_RULES_CACHE['mtime'] == mtime:
            return _SENSITIVE_RULES_CACHE['data']
        with path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        _SENSITIVE_RULES_CACHE.update({'path': path, 'mtime': mtime, 'data': data})
        return data
    except Exception:
        # 词典缺失或解析失败：降级为空规则，不影响其它检查
        return {}

_AD_EXTREME_CACHE = {'path': None, 'mtime': 0, 'data': {}}

def _load_ad_extreme_words() -> List[str]:
    """加载服务端广告法极限词词典；带 mtime 缓存，词表更新后自动热加载。"""
    path = Path(__file__).with_name('data') / 'ad_extreme_words.json'
    try:
        mtime = path.stat().st_mtime
        if _AD_EXTREME_CACHE['path'] == path and _AD_EXTREME_CACHE['mtime'] == mtime:
            return _AD_EXTREME_CACHE['data']
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        words = [w for w in (data.get('extreme_words') or []) if w and w.strip()]
        _AD_EXTREME_CACHE.update({'path': path, 'mtime': mtime, 'data': words})
        return words
    except Exception:
        # 词典缺失或解析失败：降级为空词表，不影响其它检查
        return []

# ============================================================
# 敏感信息（PII）合规扫描：校验辅助函数
# ============================================================

def _luhn_valid(num: str) -> bool:
    """Luhn 算法校验（银行卡号等）。"""
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _valid_id_card(s: str) -> bool:
    """校验 18 位居民身份证号（GB 11643-1999：出生日期合法 + 校验位正确）。"""
    if not re.fullmatch(r'\d{17}[\dXx]', s):
        return False
    try:
        y, m, d = int(s[6:10]), int(s[10:12]), int(s[12:14])
        if not (1900 <= y <= datetime.datetime.now().year):
            return False
        datetime.datetime(y, m, d)
    except Exception:
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = '10X98765432'
    su = sum(int(s[i]) * weights[i] for i in range(17))
    return check_codes[su % 11] == s[17].upper()


# 纯数字串（11-19 位）及末位为 X/x 的 18 位身份证候选，用于分类身份证/银行卡/手机号
_PI_DIGIT_RUN = re.compile(r'(?<!\d)(\d{17}[0-9Xx]|\d{11,19})(?!\d)')
# 邮箱
_PI_EMAIL_PAT = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
# 密钥/凭证：高精确度签名，尽量降低误报
_PI_KEY_PATS = [
    re.compile(r'AKIA[0-9A-Z]{16}'),                       # AWS Access Key ID
    re.compile(r'sk-[A-Za-z0-9_\-]{20,}'),                 # OpenAI
    re.compile(r'AIza[0-9A-Za-z_\-]{35}'),                 # Google API
    re.compile(r'xox[baprs]-[0-9A-Za-z\-]{10,}'),          # Slack
    re.compile(r'ghp_[0-9A-Za-z]{36}'),                    # GitHub Personal Access Token
    re.compile(r'(?:Bearer\s+)[A-Za-z0-9_\-\.=]{16,}'),    # Bearer Token
    re.compile(r'(?:api[_-]?key|token|secret|access[_-]?token|password|passwd|pwd)["\'\s]*[:=]\s*["\']?[A-Za-z0-9_\-./+]{8,}'),  # 赋值式凭证
]


# ============================================================
# 内置术语等价词表（用于「术语一致性」检测）
# 同一组内的多种写法指代同一内容，若文档同时出现其中≥2种，提示统一。
# 说明：这是开箱即用的常见等价集合；用户自定义的「术语表」(original→standard)
#       仍是更精确的强制统一手段，二者互补。
# ============================================================
TERM_EQUIVALENCES = [
    # 公司 / 品牌
    ['苹果公司', 'Apple公司', 'Apple', 'Apple Inc.', '蘋果公司'],
    ['谷歌', 'Google', '谷歌公司', 'Google公司'],
    ['微软', 'Microsoft', '微软公司', 'Microsoft公司'],
    ['腾讯', 'Tencent', '腾讯公司'],
    ['字节跳动', 'ByteDance'],
    ['亚马逊', 'Amazon'],
    ['脸书', 'Facebook', 'Meta'],
    ['特斯拉', 'Tesla'],
    ['华为', 'Huawei', '华为公司'],
    ['阿里巴巴', 'Alibaba', '阿里'],
    # 技术 / 缩略语
    ['人工智能', 'AI'],
    ['机器学习', 'ML'],
    ['深度学习', 'DL'],
    ['虚拟现实', 'VR'],
    ['增强现实', 'AR'],
    ['混合现实', 'MR'],
    ['自然语言处理', 'NLP'],
    ['物联网', 'IoT'],
    ['区块链', 'Blockchain', '区块链'],
    ['应用程序', 'APP', 'App'],
    ['操作系统', 'OS'],
    ['数据库', 'Database'],
    ['云计算', 'Cloud Computing', '云服务'],
    # 机构 / 医学
    ['新冠病毒', 'COVID-19', '新冠肺炎', 'COVID'],
    ['世界卫生组织', 'WHO'],
    ['联合国', 'UN'],
    ['国际货币基金组织', 'IMF'],
    # 地名
    ['北京', '北京市'],
    ['上海', '上海市'],
    ['美国', 'USA', 'United States', '美利坚合众国'],
    ['英国', 'UK', 'United Kingdom'],
]


# ============================================================
# 检查场景配置
# 每个场景定义：skip_types=跳过的检查类型，downgrade_types=降权(info→不报告)的检查类型
# ============================================================
SCENARIO_CONFIG = {
    'general': {
        'name': '通用文档',
        'description': '五层全面检查，适用于日常各类文本',
        'skip_types': set(),
        'downgrade_types': set(),
    },
    'academic': {
        'name': '学术论文',
        'description': '侧重术语规范、引号格式、数字规范、标点符号',
        'skip_types': {'colloquial'},            # 学术论文本身偏正式，口语化检查无意义
        'downgrade_types': {'repetition', 'style'},
    },
    'business': {
        'name': '商务文档',
        'description': '侧重错别字、全半角、标点、数字格式',
        'skip_types': {'colloquial'},            # 商务文档偏正式
        'downgrade_types': {'style'},
    },
    'legal': {
        'name': '法律文书',
        'description': '侧重严谨性、逻辑、术语一致性、标点规范',
        'skip_types': {'colloquial', 'style'},   # 法律文书有固定格式和语体
        'downgrade_types': {'repetition'},
    },
    'news': {
        'name': '新闻稿',
        'description': '侧重错别字、标点规范、口语化、时效术语',
        'skip_types': set(),                     # 新闻稿全部检查，包括口语化
        'downgrade_types': set(),
    },
    'technical': {
        'name': '技术文档',
        'description': '侧重术语一致性、全半角、数字格式、标点规范',
        'skip_types': {'colloquial', 'idiom_misuse'},  # 技术文档不检查成语和口语化
        'downgrade_types': {'style'},
    },
}


# ============================================================
# 规则数据
# ============================================================

# 中文常见错别字（错误词 -> (正确词, 说明)）
CHINESE_TYPOS = {
    '帐号': ('账号', '财务相关用字规范为「账」'),
    '帐户': ('账户', '财务相关用字规范为「账」'),
    '帐单': ('账单', '财务相关用字规范为「账」'),
    '帐目': ('账目', '财务相关用字规范为「账」'),
    '帐款': ('账款', '财务相关用字规范为「账」'),
    '帐本': ('账本', '财务相关用字规范为「账」'),
    '按装': ('安装', '「按」为误字，应为「安」'),
    '震憾': ('震撼', '「憾」应为「撼」'),
    '烦燥': ('烦躁', '「燥」应为「躁」'),
    '气慨': ('气概', '「慨」应为「概」'),
    '膺品': ('赝品', '「膺」应为「赝」'),
    '按奈': ('按捺', '「奈」应为「捺」'),
    '一股作气': ('一鼓作气', '「股」应为「鼓」'),
    '悬梁刺骨': ('悬梁刺股', '「骨」应为「股」'),
    '融汇贯通': ('融会贯通', '「汇」应为「会」'),
    '默守成规': ('墨守成规', '「默」应为「墨」'),
    '迫不急待': ('迫不及待', '「急」应为「及」'),
    '变本加利': ('变本加厉', '「利」应为「厉」'),
    '走头无路': ('走投无路', '「头」应为「投」'),
    '拾人牙惠': ('拾人牙慧', '「惠」应为「慧」'),
    '甘败下风': ('甘拜下风', '「败」应为「拜」'),
    '始终不逾': ('始终不渝', '「逾」应为「渝」'),
    '无微不致': ('无微不至', '「致」应为「至」'),
    '不可思异': ('不可思议', '「异」应为「议」'),
    '名列前矛': ('名列前茅', '「矛」应为「茅」'),
    '巧夺天功': ('巧夺天工', '「功」应为「工」'),
    '破斧沉舟': ('破釜沉舟', '「斧」应为「釜」'),
    '滥芋充数': ('滥竽充数', '「芋」应为「竽」'),
    '原形必露': ('原形毕露', '「必」应为「毕」'),
    '浮想连翩': ('浮想联翩', '「连」应为「联」'),
    '貌和神离': ('貌合神离', '「和」应为「合」'),
    '汗流夹背': ('汗流浃背', '「夹」应为「浃」'),
    '陈词烂调': ('陈词滥调', '「烂」应为「滥」'),
    '不径而走': ('不胫而走', '「径」应为「胫」'),
    '按步就班': ('按部就班', '「步」应为「部」'),
    '鞭辟入理': ('鞭辟入里', '「理」应为「里」'),
    '关怀倍至': ('关怀备至', '「倍」应为「备」'),
    '好高鹜远': ('好高骛远', '「鹜」应为「骛」'),
    '黄梁美梦': ('黄粱美梦', '「梁」应为「粱」'),
    '流光异彩': ('流光溢彩', '「异」应为「溢」'),
    '鬼鬼崇崇': ('鬼鬼祟祟', '「崇」应为「祟」'),
    '饮鸠止渴': ('饮鸩止渴', '「鸠」应为「鸩」'),
    '如火如茶': ('如火如荼', '「茶」应为「荼」'),
    '贪脏枉法': ('贪赃枉法', '「脏」应为「赃」'),
    '脍灸人口': ('脍炙人口', '「灸」应为「炙」'),
    '委屈求全': ('委曲求全', '「屈」应为「曲」'),
    '声名雀起': ('声名鹊起', '「雀」应为「鹊」'),
    '凭心而论': ('平心而论', '「凭」应为「平」'),
    '事得其反': ('适得其反', '「事」应为「适」'),
    '谈笑风声': ('谈笑风生', '「声」应为「生」'),
    '不加思索': ('不假思索', '「加」应为「假」'),
    '一诺千斤': ('一诺千金', '「斤」应为「金」'),
    '鼎立相助': ('鼎力相助', '「立」应为「力」'),
    '人情事故': ('人情世故', '「事」应为「世」'),
    '人才汇萃': ('人才荟萃', '「汇」应为「荟」'),
    '颠复': ('颠覆', '「复」应为「覆」'),
    '松驰': ('松弛', '「驰」应为「弛」'),
    '一张一驰': ('一张一弛', '「驰」应为「弛」'),
    '泊来品': ('舶来品', '「泊」应为「舶」'),
    '侯车室': ('候车室', '「侯」应为「候」'),
    '侯选人': ('候选人', '「侯」应为「候」'),
    '冒然': ('贸然', '「冒」应为「贸」'),
    '幅射': ('辐射', '「幅」应为「辐」'),
    '天翻地复': ('天翻地覆', '「复」应为「覆」'),
    '言简意骇': ('言简意赅', '「骇」应为「赅」'),
    '不落巢臼': ('不落窠臼', '「巢」应为「窠」'),
    '脏款': ('赃款', '「脏」应为「赃」'),
    '装祯': ('装帧', '「祯」应为「帧」'),
    '渡假': ('度假', '「渡」应为「度」'),
    '欢渡': ('欢度', '「渡」应为「度」'),
    '兰天白云': ('蓝天白云', '「兰」应为「蓝」'),
    '九州': None,  # 正确用法，跳过
    '九洲': ('九州', '「洲」应为「州」'),
    '做月子': ('坐月子', '「做」应为「坐」'),
    '蓝球': ('篮球', '「蓝」应为「篮」'),
    '乒乓': None,  # 正确
    '既使': ('即使', '「既」应为「即」'),
    '做为': ('作为', '「做」应为「作」（在表示身份、角色时）'),
    '那就是说': None,  # 正确
    '涉及到': ('涉及', '「涉及」已含「到」之意，无需加「到」'),
    '付诸于': ('付诸', '「诸」已为兼词（之于），无需再加「于」'),
    '凯旋归来': ('凯旋', '「凯旋」已含归来之意，无需加「归来」'),
    '共同一': None,
    '免费赠送': ('赠送', '「赠送」已含免费之意，语义重复'),
    '互相厮打': ('厮打', '「厮打」已含互相之意，语义重复'),
    '第一天子': None,
    '过度': None,  # 正确
    '过渡': None,  # 正确
    '尤其': None,  # 正确
    '制约': None,  # 正确
    '制约着': None,
    '称之为': None,  # 正确
    '堪称': None,  # 正确
}

# 英文常见拼写错误（错误 -> 正确）
ENGLISH_MISSPELLINGS = {
    'recieve': 'receive', 'occured': 'occurred', 'seperate': 'separate',
    'definately': 'definitely', 'neccessary': 'necessary', 'occassion': 'occasion',
    'accomodate': 'accommodate', 'arguement': 'argument', 'beleive': 'believe',
    'calender': 'calendar', 'cemetary': 'cemetery', 'changable': 'changeable',
    'collegue': 'colleague', 'comming': 'coming', 'commitee': 'committee',
    'concious': 'conscious', 'definitly': 'definitely', 'desireable': 'desirable',
    'disipline': 'discipline', 'embarass': 'embarrass', 'enviroment': 'environment',
    'existance': 'existence', 'experiance': 'experience', 'familar': 'familiar',
    'finaly': 'finally', 'florescent': 'fluorescent', 'foriegn': 'foreign',
    'goverment': 'government', 'gramar': 'grammar', 'happend': 'happened',
    'harras': 'harass', 'knowlege': 'knowledge', 'liason': 'liaison',
    'libary': 'library', 'lisence': 'license', 'maintainance': 'maintenance',
    'millenium': 'millennium', 'noticable': 'noticeable', 'persistant': 'persistent',
    'posession': 'possession', 'prefered': 'preferred', 'priviledge': 'privilege',
    'probaly': 'probably', 'publically': 'publicly', 'realy': 'really',
    'recomend': 'recommend', 'refered': 'referred', 'religous': 'religious',
    'repetion': 'repetition', 'rythm': 'rhythm', 'sieze': 'seize',
    'similiar': 'similar', 'sincerly': 'sincerely', 'speach': 'speech',
    'tommorow': 'tomorrow', 'tounge': 'tongue', 'truely': 'truly',
    'unfortunatly': 'unfortunately', 'untill': 'until', 'wierd': 'weird',
    'writeing': 'writing', 'alot': 'a lot', 'thier': 'their',
    'tommorrow': 'tomorrow', 'wich': 'which', 'thru': 'through',
    'thier': 'their', 'occassionally': 'occasionally', 'accross': 'across',
    'adress': 'address', 'allmost': 'almost', 'allready': 'already',
    'allways': 'always', 'apparant': 'apparent', 'appearence': 'appearance',
    'becuase': 'because', 'begining': 'beginning', 'buisness': 'business',
    'camoflauge': 'camouflage', 'carefull': 'careful', 'carrer': 'career',
    'catagory': 'category', 'cliches': 'cliches', 'collaegue': 'colleague',
    'completly': 'completely', 'controled': 'controlled', 'convenient': None,
    'criticised': None, 'defendent': 'defendant', 'definatly': 'definitely',
    'dependant': None, 'desination': 'destination', 'dissapoint': 'disappoint',
    'dissappear': 'disappear', 'dissaster': 'disaster', 'dose': 'does',
    'doubtfull': 'doubtful', 'drinkable': None, 'eigth': 'eighth',
    'embarras': 'embarrass', 'enviromental': 'environmental', 'exagerate': 'exaggerate',
    'excellant': 'excellent', 'expresso': 'espresso', 'extreme': None,
    'facillitate': 'facilitate', 'firey': 'fiery', 'flourescent': 'fluorescent',
    'forseeable': 'foreseeable', 'fourtune': 'fortune', 'freind': 'friend',
    'furneral': 'funeral', 'gaurd': 'guard', 'grammer': 'grammar',
    'happyness': 'happiness', 'harrased': 'harassed', 'heirarchy': 'hierarchy',
    'hellow': 'hello', 'hierachy': 'hierarchy', 'honour': None,
    'horrifyed': 'horrified', 'humerous': 'humorous', 'hygenic': 'hygienic',
    'hypocracy': 'hypocrisy', 'idiosyncracy': 'idiosyncrasy', 'imitiate': 'imitate',
    'immidiately': 'immediately', 'independant': 'independent', 'indispensible': 'indispensable',
    'innoculate': 'inoculate', 'intelectual': 'intellectual', 'inteligent': 'intelligent',
    'interupt': 'interrupt', 'irresistable': 'irresistible', 'jist': 'gist',
    'judgement': None, 'knowlegable': 'knowledgeable', 'labatory': 'laboratory',
    'lenght': 'length', 'liason': 'liaison', 'liesure': 'leisure',
    'lightening': None, 'liquify': 'liquefy', 'loathe': None,
    'loose': None, 'loosing': 'losing', 'maintainance': 'maintenance',
    'managable': 'manageable', 'maneuver': None, 'medeval': 'medieval',
    'millepede': 'millipede', 'miniscule': 'minuscule', 'mischievious': 'mischievous',
    'mispell': 'misspell', 'momento': 'memento', 'mosquito': None,
    'necesary': 'necessary', 'noticable': 'noticeable', 'noticably': 'noticeably',
    'nucular': 'nuclear', 'ommision': 'omission', 'orignal': 'original',
    'outragous': 'outrageous', 'pavillion': 'pavilion', 'percieve': 'perceive',
    'perseverence': 'perseverance', 'personell': 'personnel', 'persue': 'pursue',
    'picnic': None, 'playright': 'playwright', 'posession': 'possession',
    'posession': 'possession', 'possesion': 'possession', 'potatos': 'potatoes',
    'prefered': 'preferred', 'presense': 'presence', 'primative': 'primitive',
    'priviledge': 'privilege', 'professer': 'professor', 'promiss': 'promise',
    'pronounciation': 'pronunciation', 'prophecey': 'prophecy', 'quanitity': 'quantity',
    'questionaire': 'questionnaire', 'quizes': 'quizzes', 'realy': 'really',
    'reccomend': 'recommend', 'reciept': 'receipt', 'recieve': 'receive',
    'rediculous': 'ridiculous', 'reguard': 'regard', 'relevent': 'relevant',
    'religous': 'religious', 'repitition': 'repetition', 'resistence': 'resistance',
    'rythm': 'rhythm', 'secratary': 'secretary', 'seige': 'siege',
    'seperate': 'separate', 'sheild': 'shield', 'sieze': 'seize',
    'similer': 'similar', 'sincerly': 'sincerely', 'speach': 'speech',
    'supercede': 'supersede', 'supress': 'suppress', 'surprize': 'surprise',
    'tempature': 'temperature', 'tendancy': 'tendency', 'threshhold': 'threshold',
    'tommorow': 'tomorrow', 'tounge': 'tongue', 'twelth': 'twelfth',
    'tyrany': 'tyranny', 'underate': 'underrate', 'untill': 'until',
    'upholstry': 'upholstery', 'usable': None, 'vaccum': 'vacuum',
    'vehical': 'vehicle', 'wierd': 'weird', 'wellfare': 'welfare',
    'wilfull': 'willful', 'writting': 'writing', 'yatch': 'yacht',
    'yeild': 'yield',
}

# 中文标点 -> 对应的英文标点（用于检测中英标点混用）
CN_PUNCT_MAP = {
    '，': ',', '。': '.', '；': ';', '：': ':',
    '！': '!', '？': '?', '（': '(', '）': ')',
    '「': '"', '」': '"', '『': '"', '』': '"',
    '【': '[', '】': ']', '《': '<', '》': '>',
}
EN_PUNCT_IN_CN_CONTEXT = {',', '.', ';', ':', '!', '?', '(', ')'}

# 中文常见搭配错误（的/地/得）
DE_USAGE_RULES = [
    # (pattern, description, suggestion_template)
    (re.compile(r'([\u4e00-\u9fa5])的([\u4e00-\u9fa5])'), None),  # 太宽泛，不直接用
]

# 重复词语检测的停用词
REPEAT_STOPWORDS = {'的', '了', '是', '在', '也', '都', '就', '还', '又', '才', '再', '都', '而'}

# 关联词配对表（前半句 -> [可能的后半句], 说明）
# 说明：「因为」「由于」作为因果介词可独立引导原因，无需强制配对「所以/因此」，
#       故不列入严格配对，避免大量误报。
PAIRED_CONJUNCTIONS = [
    ('虽然', ['但是', '却', '然而', '可是', '但仍', '但还'], '虽然……但是/却'),
    ('尽管', ['但是', '却', '然而', '可是', '但仍', '但还'], '尽管……但是/却'),
    ('不但', ['而且', '还', '也'], '不但……而且'),
    ('不仅', ['而且', '还', '也'], '不仅……而且'),
    ('既然', ['就', '那'], '既然……就'),
    ('只要', ['就'], '只要……就'),
    ('只有', ['才'], '只有……才'),
    ('无论', ['都', '也'], '无论……都'),
    ('不管', ['都', '也'], '不管……都'),
    ('与其', ['不如'], '与其……不如'),
    ('宁可', ['也不', '也要'], '宁可……也不/也要'),
    ('即使', ['也'], '即使……也'),
    ('哪怕', ['也'], '哪怕……也'),
    ('一方面', ['另一方面'], '一方面……另一方面'),
]

# 常见四字成语（用于检测缺字）
COMMON_IDIOMS = [
    '一帆风顺', '一目了然', '一丝不苟', '一鸣惊人', '一诺千金',
    '一鼓作气', '一蹴而就', '一蹶不振', '一视同仁', '一知半解',
    '不可思议', '不可一世', '不约而同', '不耻下问', '不屈不挠',
    '不约而同', '不言而喻', '不翼而飞', '不速之客', '不假思索',
    '不劳而获', '不谋而合', '不约而同', '不寒而栗', '不拘一格',
    '顺理成章', '顺水推舟', '随心所欲', '随波逐流', '随机应变',
    '迎刃而解', '迎刃而上', '奋不顾身', '奋发图强', '奋起直追',
    '迫不及侍', '迫不及待', '破釜沉舟', '破镜重圆', '破旧立新',
    '理所当然', '理直气壮', '畅所欲言', '畅行无阻', '畅达通畅',
    '循序渐进', '渐入佳境', '潜移默化', '潜藏隐患', '潜移默化',
    '显而易见', '鲜为人知', '鲜有其匹', '相辅相成', '相得益彰',
    '实事求是', '脚踏实地', '竭尽全力', '竭诚服务', '竭泽而渔',
    '举一反三', '举足轻重', '举世瞩目', '举世无双', '举重若轻',
    '恰到好处', '恰如其分', '适可而止', '适逢其会', '适者生存',
    '众志成城', '众望所归', '众口一词', '众矢之的', '众所周知',
    '无可厚非', '无微不至', '无与伦比', '无可非议', '无可争辩',
    '无懈可击', '无言以对', '无影无踪', '无人问津', '无济于事',
    '有目共睹', '有口皆碑', '有条不紊', '有恃无恐', '有备无患',
    '因地制宜', '因势利导', '因小失大', '因噎废食', '因循守旧',
    '言简意赅', '言而有信', '言出必行', '言传身教', '言过其实',
    '行之有效', '行云流水', '行将就木', '行若无事', '行不顾言',
    '如火如荼', '如释重负', '如鱼得水', '如虎添翼', '如履薄冰',
    '循序渐进', '欣欣向荣', '欣欣然然', '汗牛充栋', '汗马功劳',
    '融会贯通', '融会贯通', '墨守成规', '潜移默化', '精益求精',
    '精益求精', '精打细算', '精兵简政', '精神焕发', '精诚团结',
    '胸有成竹', '胸无点墨', '胸怀大志', '胸襟开阔', '胸中无数',
    '顺其自然', '顺水推舟', '顺风顺水', '顺藤摸瓜', '顺理成章',
    '理所当然', '理直气壮', '理直气壮', '理屈词穷', '理所当然',
    '马到成功', '马不停蹄', '马首是瞻', '马革裹尸', '马齿徒增',
    '胸有成竹', '胸有成略', '胸有丘壑', '胸有城府', '胸有成竹',
    '显而易见', '显而易见', '彰明较著', '昭然若揭', '昭然在目',
    '迫不及待', '迫在眉睫', '迫不得已', '迫于无奈', '迫在眼前',
    '刻不容缓', '刻骨铭心', '刻舟求剑', '刻鹄类鹜', '刻意求工',
    '层出不穷', '层峦叠嶂', '层出不穷', '层见叠出', '层峦叠翠',
    '理所当然', '理直气壮', '理屈词穷', '理所当然', '理不胜辞',
    '毋庸置疑', '毋庸讳言', '毋庸置疑', '母以子贵', '母婴同室',
    '显而易见', '显而易见', '旗帜鲜明', '旗帜鲜明', '旗开得胜',
    '首当其冲', '首屈一指', '首善之区', '首尾相应', '首鼠两端',
    '显而易见', '显而易见', '显而易见', '显而易见', '显而易见',
]

# 常见固定搭配缺字（残缺短语 -> (完整短语, 说明)）
INCOMPLETE_PHRASES = {
    '迫不及': ('迫不及待', '「迫不及待」缺少「待」字'),
    '不言而': ('不言而喻', '「不言而喻」缺少「喻」字'),
    '不约而': ('不约而同', '「不约而同」缺少「同」字'),
    '一知半': ('一知半解', '「一知半解」缺少「解」字'),
    '一鼓作': ('一鼓作气', '「一鼓作气」缺少「气」字'),
    '一帆风': ('一帆风顺', '「一帆风顺」缺少「顺」字'),
    '一丝不': ('一丝不苟', '「一丝不苟」缺少「苟」字'),
    '不假思': ('不假思索', '「不假思索」缺少「索」字'),
    '理所当': ('理所当然', '「理所当然」缺少「然」字'),
    '顺理成': ('顺理成章', '「顺理成章」缺少「章」字'),
    '无微不': ('无微不至', '「无微不至」缺少「至」字'),
    '有目共': ('有目共睹', '「有目共睹」缺少「睹」字'),
    '举一反': ('举一反三', '「举一反三」缺少「三」字'),
    '相辅相': ('相辅相成', '「相辅相成」缺少「成」字'),
    '相得益': ('相得益彰', '「相得益彰」缺少「彰」字'),
    '破釜沉': ('破釜沉舟', '「破釜沉舟」缺少「舟」字'),
    '墨守成': ('墨守成规', '「墨守成规」缺少「规」字'),
    '融会贯': ('融会贯通', '「融会贯通」缺少「通」字'),
    '潜移默': ('潜移默化', '「潜移默化」缺少「化」字'),
    '精打细': ('精打细算', '「精打细算」缺少「算」字'),
    '胸有成': ('胸有成竹', '「胸有成竹」缺少「竹」字'),
    '旗开得': ('旗开得胜', '「旗开得胜」缺少「胜」字'),
    '首屈一': ('首屈一指', '「首屈一指」缺少「指」字'),
    '刻不容': ('刻不容缓', '「刻不容缓」缺少「缓」字'),
    '层出不穷': None,  # 完整，跳过
    '迎刃而解': None,  # 完整
    '循序渐进': None,
    '实事求是': None,
    '恰到好处': None,
    '众志成城': None,
    '因地制宜': None,
    '言简意赅': None,
    '行之有效': None,
    '无可厚非': None,
    '理所当然': None,
    '迫不及待': None,
    '不可一世': None,
    '不约而同': None,
    '不言而喻': None,
    '一丝不苟': None,
    '一目了然': None,
    '一帆风顺': None,
    '一鸣惊人': None,
    '一诺千金': None,
    '不假思索': None,
    '无微不至': None,
    '有目共睹': None,
    '举一反三': None,
    '相辅相成': None,
    '相得益彰': None,
    '破釜沉舟': None,
    '墨守成规': None,
    '融会贯通': None,
    '潜移默化': None,
    '精打细算': None,
    '胸有成竹': None,
    '旗开得胜': None,
    '首屈一指': None,
    '刻不容缓': None,
    '顺理成章': None,
    '理直气壮': None,
    '举足轻重': None,
    '马到成功': None,
    '如火如荼': None,
    '汗牛充栋': None,
    '有口皆碑': None,
    '有条不紊': None,
    '有备无患': None,
    '因势利导': None,
    '言而有信': None,
    '行云流水': None,
    '如释重负': None,
    '如鱼得水': None,
    '如虎添翼': None,
    '如履薄冰': None,
    '马不停蹄': None,
    '毋庸置疑': None,
    '随心所欲': None,
    '随波逐流': None,
    '随机应变': None,
    '奋不顾身': None,
    '奋发图强': None,
    '适可而止': None,
    '众望所归': None,
    '众所周知': None,
    '无可非议': None,
    '无懈可击': None,
    '举世瞩目': None,
    '恰如其分': None,
    '畅所欲言': None,
    '竭尽全力': None,
    '无与伦比': None,
    '显而易见': None,
    '鲜为人知': None,
    '不翼而飞': None,
    '不速之客': None,
    '不寒而栗': None,
    '不拘一格': None,
    '不屈不挠': None,
    '不耻下问': None,
    '不谋而合': None,
    '一视同仁': None,
    '一蹴而就': None,
    '一蹶不振': None,
    '举重若轻': None,
    '破镜重圆': None,
    '顺水推舟': None,
    '顺其自然': None,
    '理屈词穷': None,
    '无影无踪': None,
    '无人问津': None,
    '无济于事': None,
    '有恃无恐': None,
    '因小失大': None,
    '因噎废食': None,
    '因循守旧': None,
    '言出必行': None,
    '言过其实': None,
    '如释重负': None,
    '汗马功劳': None,
    '精诚团结': None,
    '精神焕发': None,
    '精兵简政': None,
    '迫在眉睫': None,
    '迫不得已': None,
    '刻骨铭心': None,
    '刻舟求剑': None,
    '层峦叠嶂': None,
    '首当其冲': None,
    '首鼠两端': None,
    '破旧立新': None,
    '奋发图强': None,
    '奋起直追': None,
}


# 常见异形词（推荐词形 -> (非推荐词形, 说明)）
# 参考《第一批异形词整理表》
VARIANT_WORDS = {
    '账户': ('帐户', '推荐使用「账户」，「帐户」为非推荐词形'),
    '账号': ('帐号', '推荐使用「账号」，「帐号」为非推荐词形'),
    '账单': ('帐单', '推荐使用「账单」，「帐单」为非推荐词形'),
    '账目': ('帐目', '推荐使用「账目」，「帐目」为非推荐词形'),
    '账款': ('帐款', '推荐使用「账款」，「帐款」为非推荐词形'),
    '账本': ('帐本', '推荐使用「账本」，「帐本」为非推荐词形'),
    '角色': ('脚色', '推荐使用「角色」'),
    '搭档': ('搭当', '推荐使用「搭档」'),
    '溜达': ('蹓跶', '推荐使用「溜达」'),
    '车厢': ('车箱', '推荐使用「车厢」'),
    '订货': ('定货', '推荐使用「订货」'),
    '订购': ('定购', '推荐使用「订购」'),
    '订阅': ('定阅', '推荐使用「订阅」'),
    '订单': ('定单', '推荐使用「订单」'),
    '定价': ('定价', None),  # 两可
    '抹杀': ('抹煞', '推荐使用「抹杀」'),
    '折磨': ('折魔', '推荐使用「折磨」'),
    '辈分': ('辈份', '推荐使用「辈分」'),
    '分量': ('份量', '推荐使用「分量」'),
    '身份': ('身分', '推荐使用「身份」'),
    '图像': ('图象', '推荐使用「图像」'),
    '录像': ('录象', '推荐使用「录像」'),
    '想象': ('想像', '推荐使用「想象」'),
    '象征': ('象徵', '推荐使用「象征」'),
    '交代': ('交待', '推荐使用「交代」'),
    '过年': ('過年', None),  # 繁体不在此检测
}

# 异形/不规范单字（非规范字形 -> (规范字形, 说明)）
# 包含 CJK 部首补充、康熙部首等不应作为普通文本出现的字符
IRREGULAR_CHARS = {
    # CJK Radicals Supplement (U+2E80-U+2EFF) 中可能混入正文的部首
    '⻔': ('门', '「⻔」为部首字形，正文应使用「门」'),
    '⻳': ('龟', '「⻳」为部首字形，正文应使用「龟」'),
    '⻰': ('龙', '「⻰」为部首字形，正文应使用「龙」'),
    '⻢': ('马', '「⻢」为部首字形，正文应使用「马」'),
    '⻛': ('风', '「⻛」为部首字形，正文应使用「风」'),
    '⻜': ('飞', '「⻜」为部首字形，正文应使用「飞」'),
    '⻤': ('鬼', '「⻤」为部首字形，正文应使用「鬼」'),
    '⻥': ('鱼', '「⻥」为部首字形，正文应使用「鱼」'),
    '⻦': ('鸟', '「⻦」为部首字形，正文应使用「鸟」'),
    '⻧': ('卤', '「⻧」为部首字形，正文应使用「卤」'),
    '⻨': ('麦', '「⻨」为部首字形，正文应使用「麦」'),
    '⻩': ('黄', '「⻩」为部首字形，正文应使用「黄」'),
    '⻪': ('龟', '「⻪」为部首字形，正文应使用「龟」'),
    '⻫': ('齐', '「⻫」为部首字形，正文应使用「齐」'),
    '⻬': ('齐', '「⻬」为部首字形，正文应使用「齐」'),
    '⻭': ('齿', '「⻭」为部首字形，正文应使用「齿」'),
    '⻮': ('齿', '「⻮」为部首字形，正文应使用「齿」'),
    '⻯': ('龙', '「⻯」为部首字形，正文应使用「龙」'),
    '⻱': ('龟', '「⻱」为部首字形，正文应使用「龟」'),
    '⻲': ('龟', '「⻲」为部首字形，正文应使用「龟」'),
    '⻵': ('门', '「⻵」为部首字形，正文应使用「门」'),
    '⻶': ('斗', '「⻶」为部首字形，正文应使用「斗」'),
    '⻷': ('斗', '「⻷」为部首字形，正文应使用「斗」'),
    '⻸': ('斗', '「⻸」为部首字形，正文应使用「斗」'),
    '⻹': ('斗', '「⻹」为部首字形，正文应使用「斗」'),
    '⻺': ('斗', '「⻺」为部首字形，正文应使用「斗」'),
    '⻻': ('斗', '「⻻」为部首字形，正文应使用「斗」'),
    # Kangxi Radicals (U+2F00-U+2FD5) 中可能混入正文的部首
    '⼀': ('一', '「⼀」为部首字形，正文应使用「一」'),
    '⼆': ('二', '「⼆」为部首字形，正文应使用「二」'),
    '⼈': ('人', '「⼈」为部首字形，正文应使用「人」'),
    '⼊': ('入', '「⼊」为部首字形，正文应使用「入」'),
    '⼏': ('几', '「⼏」为部首字形，正文应使用「几」'),
    '⼝': ('口', '「⼝」为部首字形，正文应使用「口」'),
    '⼟': ('土', '「⼟」为部首字形，正文应使用「土」'),
    '⼤': ('大', '「⼤」为部首字形，正文应使用「大」'),
    '⼥': ('女', '「⼥」为部首字形，正文应使用「女」'),
    '⼦': ('子', '「⼦」为部首字形，正文应使用「子」'),
    '⼩': ('小', '「⼩」为部首字形，正文应使用「小」'),
    '⼭': ('山', '「⼭」为部首字形，正文应使用「山」'),
    '⼯': ('工', '「⼯」为部首字形，正文应使用「工」'),
    '⼰': ('己', '「⼰」为部首字形，正文应使用「己」'),
    '⼲': ('干', '「⼲」为部首字形，正文应使用「干」'),
    '⼼': ('心', '「⼼」为部首字形，正文应使用「心」'),
    '⼿': ('手', '「⼿」为部首字形，正文应使用「手」'),
    '⽂': ('文', '「⽂」为部首字形，正文应使用「文」'),
    '⽅': ('方', '「⽅」为部首字形，正文应使用「方」'),
    '⽆': ('无', '「⽆」为部首字形，正文应使用「无」'),
    '⽇': ('日', '「⽇」为部首字形，正文应使用「日」'),
    '⽉': ('月', '「⽉」为部首字形，正文应使用「月」'),
    '⽊': ('木', '「⽊」为部首字形，正文应使用「木」'),
    '⽔': ('水', '「⽔」为部首字形，正文应使用「水」'),
    '⽕': ('火', '「⽕」为部首字形，正文应使用「火」'),
    '⽜': ('牛', '「⽜」为部首字形，正文应使用「牛」'),
    '⽝': ('犬', '「⽝」为部首字形，正文应使用「犬」'),
    '⽟': ('玉', '「⽟」为部首字形，正文应使用「玉」'),
    '⽣': ('生', '「⽣」为部首字形，正文应使用「生」'),
    '⽤': ('用', '「⽤」为部首字形，正文应使用「用」'),
    '⽥': ('田', '「⽥」为部首字形，正文应使用「田」'),
    '⽩': ('白', '「⽩」为部首字形，正文应使用「白」'),
    '⽬': ('目', '「⽬」为部首字形，正文应使用「目」'),
    '⽯': ('石', '「⽯」为部首字形，正文应使用「石」'),
    '⽴': ('立', '「⽴」为部首字形，正文应使用「立」'),
    '⽵': ('竹', '「⽵」为部首字形，正文应使用「竹」'),
    '⽶': ('米', '「⽶」为部首字形，正文应使用「米」'),
    '⽹': ('网', '「⽹」为部首字形，正文应使用「网」'),
    '⽺': ('羊', '「⽺」为部首字形，正文应使用「羊」'),
    '⽼': ('老', '「⽼」为部首字形，正文应使用「老」'),
    '⽽': ('而', '「⽽」为部首字形，正文应使用「而」'),
    '⽿': ('耳', '「⽿」为部首字形，正文应使用「耳」'),
    '⾁': ('肉', '「⾁」为部首字形，正文应使用「肉」'),
    '⾃': ('自', '「⾃」为部首字形，正文应使用「自」'),
    '⾄': ('至', '「⾄」为部首字形，正文应使用「至」'),
    '⾊': ('色', '「⾊」为部首字形，正文应使用「色」'),
    '⾍': ('虫', '「⾍」为部首字形，正文应使用「虫」'),
    '⾎': ('血', '「⾎」为部首字形，正文应使用「血」'),
    '⾏': ('行', '「⾏」为部首字形，正文应使用「行」'),
    '⾐': ('衣', '「⾐」为部首字形，正文应使用「衣」'),
    '⾒': ('见', '「⾒」为部首字形，正文应使用「见」'),
    '⾓': ('角', '「⾓」为部首字形，正文应使用「角」'),
    '⾔': ('言', '「⾔」为部首字形，正文应使用「言」'),
    '⾕': ('谷', '「⾕」为部首字形，正文应使用「谷」'),
    '⾖': ('豆', '「⾖」为部首字形，正文应使用「豆」'),
    '⾙': ('贝', '「⾙」为部首字形，正文应使用「贝」'),
    '⾚': ('赤', '「⾚」为部首字形，正文应使用「赤」'),
    '⾛': ('走', '「⾛」为部首字形，正文应使用「走」'),
    '⾜': ('足', '「⾜」为部首字形，正文应使用「足」'),
    '⾝': ('身', '「⾝」为部首字形，正文应使用「身」'),
    '⾞': ('车', '「⾞」为部首字形，正文应使用「车」'),
    '⾦': ('金', '「⾦」为部首字形，正文应使用「金」'),
    '⾧': ('长', '「⾧」为部首字形，正文应使用「长」'),
    '⾩': ('门', '「⾩」为部首字形，正文应使用「门」'),
    '⾬': ('雨', '「⾬」为部首字形，正文应使用「雨」'),
    '⾯': ('面', '「⾯」为部首字形，正文应使用「面」'),
    '⾰': ('革', '「⾰」为部首字形，正文应使用「革」'),
    '⾵': ('风', '「⾵」为部首字形，正文应使用「风」'),
    '⾶': ('飞', '「⾶」为部首字形，正文应使用「飞」'),
    '⾷': ('食', '「⾷」为部首字形，正文应使用「食」'),
    '⾸': ('首', '「⾸」为部首字形，正文应使用「首」'),
    '⾹': ('香', '「⾹」为部首字形，正文应使用「香」'),
    '⾺': ('马', '「⾺」为部首字形，正文应使用「马」'),
    '⾻': ('骨', '「⾻」为部首字形，正文应使用「骨」'),
    '⾼': ('高', '「⾼」为部首字形，正文应使用「高」'),
    '⿁': ('鬼', '「⿁」为部首字形，正文应使用「鬼」'),
    '⿂': ('鱼', '「⿂」为部首字形，正文应使用「鱼」'),
    '⿃': ('鸟', '「⿃」为部首字形，正文应使用「鸟」'),
    '⿄': ('卤', '「⿄」为部首字形，正文应使用「卤」'),
    '⿅': ('鹿', '「⿅」为部首字形，正文应使用「鹿」'),
    '⿆': ('麦', '「⿆」为部首字形，正文应使用「麦」'),
    '⿇': ('麻', '「⿇」为部首字形，正文应使用「麻」'),
    '⿈': ('黄', '「⿈」为部首字形，正文应使用「黄」'),
    '⿊': ('黑', '「⿊」为部首字形，正文应使用「黑」'),
    '⿑': ('齐', '「⿑」为部首字形，正文应使用「齐」'),
    '⿒': ('齿', '「⿒」为部首字形，正文应使用「齿」'),
    '⿓': ('龙', '「⿓」为部首字形，正文应使用「龙」'),
    '⿔': ('龟', '「⿔」为部首字形，正文应使用「龟」'),
}

# 全角/半角混用：半角标点及其对应的全角标点
HALF_FULL_PUNCT = {
    ',': '，', '.': '。', ';': '；', ':': '：',
    '!': '！', '?': '？', '(': '（', ')': '）',
    '[': '【', ']': '】', '"': '"', '"': '"',
}

# 常见成语误用
# 格式：(正则, [替换候选1, 候选2, ...], 误用说明, 正确用法提示)
IDIOM_MISUSE = [
    (r'差强人意',
     ['不尽如人意', '令人失望', '难以令人满意'],
     '「差强人意」意为「大体上还能使人满意」，常被误用为「不能使人满意」',
     '如表达不满意，建议改为「不尽如人意」或「令人失望」'),
    (r'空穴来风',
     ['无中生有', '凭空捏造', '毫无根据'],
     '「空穴来风」意为「事出有因、传言有根据」，常被误用为「无中生有」',
     '如表达无根据，建议改为「无中生有」或「凭空捏造」'),
    (r'昨日黄花',
     ['明日黄花'],
     '「明日黄花」比喻已过时的事物，常被误写为「昨日黄花」',
     '建议改为「明日黄花」'),
    (r'七月流火',
     ['骄阳似火', '烈日当空', '酷暑难耐'],
     '「七月流火」指天气转凉，常被误用为形容天气炎热',
     '如表达天气炎热，建议改为「骄阳似火」或「烈日当空」'),
    (r'望其项背',
     ['难以望其项背', '望尘莫及', '不可企及'],
     '「望其项背」表示能赶上（看得见前人后背），常被误用为「赶不上」',
     '如表达赶不上，建议改为「难以望其项背」或「望尘莫及」'),
    (r'万人空巷',
     ['人迹罕至', '门可罗雀', '冷冷清清'],
     '「万人空巷」指人们都从巷子里出来观看，形容庆祝盛况，常被误用为「街巷空无一人」',
     '如表达冷清，建议改为「人迹罕至」或「门可罗雀」'),
    (r'不以为然',
     ['不以为意', '毫不在意', '并不在意'],
     '「不以为然」意为「不认为是对的」表示不同意，常被误用为「不放在心上」',
     '如表达不在意，建议改为「不以为意」'),
    (r'炙手可热',
     ['广受欢迎', '备受追捧', '风靡一时'],
     '「炙手可热」形容权势大、气焰盛，常被误用为形容热门流行',
     '如表达热门，建议改为「广受欢迎」或「备受追捧」'),
    (r'首当其冲',
     ['一马当先', '冲锋在前', '身先士卒'],
     '「首当其冲」比喻最先受到攻击或遭到灾难，常被误用为「冲在最前面」',
     '如表达冲在前面，建议改为「一马当先」或「冲锋在前」'),
    (r'溢美之言',
     ['溢美之词'],
     '「溢美」已含赞美之意，「溢美之词」常被误写为「溢美之言」',
     '建议使用「溢美之词」'),
]

# 口语化表达（在正式文档中不宜使用的词语/短语）
# 格式：(正则, [替换候选1, 替换候选2, ...], 问题说明)
COLLOQUIAL_EXPRESSIONS = [
    (r'然后', ['随后', '继而', '此后'], '口语化的连接词，正式文档中建议使用「随后」「继而」「此后」等'),
    (r'就是说', ['即', '也就是说', '换言之'], '口语化表达，正式文档中建议使用「即」「也就是说」等'),
    (r'所以说', ['因此', '由此可见', '故而'], '口语化表达，正式文档中建议使用「因此」「由此可见」等'),
    (r'其实吧', ['其实', '实际上', '事实上'], '口语化语气词，正式文档中不宜使用'),
    (r'反正', ['无论如何', '总之', '不管怎样'], '口语化表达，正式文档中建议使用「无论如何」「总之」等'),
    (r'咱们', ['我们', '我方', '本公司'], '口语化代词，正式文档中建议使用「我们」'),
    (r'啥', ['什么', '何种', None], '口语用字，正式文档中建议使用「什么」'),
    (r'咋', ['怎么', '如何', '怎样'], '口语用字，正式文档中建议使用「怎么」'),
    (r'特别地', ['尤其', '格外', '特别'], '口语化副词，正式文档中建议使用「尤其」「格外」等'),
    (r'非常地', ['十分', '极为', '非常'], '口语化副词，正式文档中建议使用「十分」「极为」等'),
    (r'挺好的', ['较好', '良好', '尚可'], '口语化表达，正式文档中建议使用「较好」「良好」等'),
    (r'挺不错的', ['优秀', '出色', '良好'], '口语化表达，正式文档中建议使用「优秀」「出色」等'),
    (r'搞', ['做', '进行', '完成'], '口语用字，正式文档中建议根据语境使用「做」「进行」「完成」等'),
    (r'弄', ['做', '处理', '准备'], '口语用字，正式文档中建议根据语境使用「做」「处理」「准备」等'),
    (r'咱们公司', ['本公司', '我公司', '我司'], '口语化表达，正式文档中建议使用「本公司」「我公司」'),
    (r'一块儿', ['一起', '一同', '共同'], '口语化表达，正式文档中建议使用「一起」「一同」'),
    (r'赶紧', ['尽快', '迅即', '加紧'], '口语化表达，正式文档中建议使用「尽快」「迅即」'),
    (r'马上就', ['即将', '随即', '立刻'], '口语化表达，正式文档中建议使用「即将」「随即」'),
    (r'有点儿', ['略有', '稍有', '有些'], '口语化表达，正式文档中建议使用「略有」「稍有」'),
    (r'一点儿', ['稍', '略', '些许'], '口语化表达，正式文档中建议使用「稍」「略」'),
]


class TextAnalyzer:
    """文本分析器主类"""

    def __init__(self):
        self._build_typo_patterns()

    def _build_typo_patterns(self):
        """预编译错别字正则"""
        # 中文错别字
        cn_items = [(k, v) for k, v in CHINESE_TYPOS.items() if v is not None]
        # 按长度降序排列，避免短词先匹配
        cn_items.sort(key=lambda x: len(x[0]), reverse=True)
        self._cn_typo_pattern = re.compile(
            '|'.join(re.escape(k) for k, _ in cn_items)
        )
        self._cn_typo_map = {k: v for k, v in cn_items}

        # 英文拼写错误（使用 re.ASCII 使 \b 在中文字符旁也能正确匹配）
        en_items = [(k, v) for k, v in ENGLISH_MISSPELLINGS.items() if v is not None]
        en_items.sort(key=lambda x: len(x[0]), reverse=True)
        self._en_typo_pattern = re.compile(
            r'(?<![a-zA-Z])(' + '|'.join(re.escape(k) for k, _ in en_items) + r')(?![a-zA-Z])',
            re.IGNORECASE
        )
        self._en_typo_map = {k.lower(): v for k, v in en_items}

    def analyze(self, text: str, scenario: str = 'general',
                custom_glossary: List[Dict] = None,
                banned_words: List[str] = None,
                enable_security: bool = True,
                enable_sensitive: bool = True,
                enable_ad_extreme: bool = False) -> List[Issue]:
        """分析文本，返回所有检测到的问题。
        scenario 控制不同文档类型的检查侧重。
        custom_glossary 为自定义术语表，每项 {'original': str, 'standard': str}。
        banned_words 为禁用词列表。
        enable_security 控制是否执行合规/安全层（PII）扫描；默认开启。
        enable_sensitive 控制是否执行敏感内容（涉政/民族宗教/领土规范表述）检查；默认开启。
        enable_ad_extreme 控制是否执行广告法极限词（营销材料）检查；默认关闭，需用户显式开启。
        """
        if not text or not text.strip():
            return []

        # 获取场景配置，未知场景回退到通用
        cfg = SCENARIO_CONFIG.get(scenario, SCENARIO_CONFIG['general'])
        skip_types = cfg['skip_types']
        downgrade_types = cfg['downgrade_types']

        issues: List[Issue] = []

        # === 字符层 ===
        issues.extend(self._check_chinese_typos(text))
        issues.extend(self._check_english_spelling(text))
        issues.extend(self._check_variant_chars(text))
        issues.extend(self._check_half_full_width(text))

        # === 词汇层 ===
        issues.extend(self._check_missing_chars(text))
        issues.extend(self._check_idiom_misuse(text))
        issues.extend(self._check_term_consistency(text))
        if custom_glossary:
            issues.extend(self._check_custom_glossary(text, custom_glossary))

        # === 句子层 ===
        issues.extend(self._check_expression_issues(text))
        issues.extend(self._check_grammar_patterns(text))

        # === 标点/格式层 ===
        issues.extend(self._check_punctuation(text))
        issues.extend(self._check_brackets_quotes(text))
        issues.extend(self._check_extra_spaces(text))
        issues.extend(self._check_number_format(text))

        # === 语篇/语体层 ===
        issues.extend(self._check_repeated_words(text))
        issues.extend(self._check_colloquial(text))
        if banned_words:
            issues.extend(self._check_banned_words(text, banned_words))

        # === 合规/安全层 ===
        if enable_security:
            issues.extend(self._check_pii(text))
        # 敏感内容（涉政/民族宗教/领土规范表述）独立于 PII，由各自开关控制
        if enable_sensitive:
            issues.extend(self._check_sensitive(text, _load_sensitive_rules()))
        # 广告法极限词（营销材料）检查，独立于 PII 与敏感词，由各自开关控制
        if enable_ad_extreme:
            issues.extend(self._check_ad_extreme(text, _load_ad_extreme_words()))

        # 为每个 issue 赋予 layer
        for issue in issues:
            if not issue.layer:
                issue.layer = TYPE_TO_LAYER.get(issue.type, 'discourse')

        # 场景过滤：跳过该场景不需要的检查类型
        if skip_types:
            issues = [i for i in issues if i.type not in skip_types]

        # 场景降权：将该场景次要的检查类型从 info 降级为不报告
        if downgrade_types:
            issues = [i for i in issues if not (i.type in downgrade_types and i.severity == 'info')]

        # 去重（同一位置同一类型的问题只保留一个）
        seen = set()
        unique_issues = []
        for issue in issues:
            key = (issue.type, issue.position, issue.end_position, issue.original)
            if key not in seen:
                seen.add(key)
                unique_issues.append(issue)

        # 二次去重：同一文本片段（起始位置 + 原文）若被多个规则/类型重复标记
        # （例如半角逗号「,」同时被「全半角混用」与「标点符号」命中，给出相同的
        # 「，」修正），只保留一条，避免用户在批量替换时看到重复项、误以为未替换干净。
        # 冲突时按优先级归并：标点/空格类优先于全半角，更贴合当前问题的关注点。
        _type_priority = {
            'punctuation': 0, 'spacing': 0,
            'width_mixed': 1,
        }
        span_best = {}
        for issue in unique_issues:
            skey = (issue.position, issue.end_position, issue.original)
            if skey not in span_best:
                span_best[skey] = issue
            else:
                exist = span_best[skey]
                if _type_priority.get(issue.type, 9) < _type_priority.get(exist.type, 9):
                    span_best[skey] = issue
        deduped = list(span_best.values())

        # 按位置排序
        deduped.sort(key=lambda x: (x.position, x.end_position))
        return deduped

    def _get_context(self, text: str, start: int, end: int, radius: int = 15) -> str:
        """获取问题文本的上下文"""
        ctx_start = max(0, start - radius)
        ctx_end = min(len(text), end + radius)
        prefix = '...' if ctx_start > 0 else ''
        suffix = '...' if ctx_end < len(text) else ''
        return f"{prefix}{text[ctx_start:ctx_end]}{suffix}"

    # ============================================================
    # 检查规则
    # ============================================================

    def _check_chinese_typos(self, text: str) -> List[Issue]:
        """中文常见错别字检测"""
        issues = []
        for match in self._cn_typo_pattern.finditer(text):
            word = match.group()
            if word in self._cn_typo_map:
                correct, desc = self._cn_typo_map[word]
                issues.append(Issue(
                    type='typo',
                    severity='error',
                    original=word,
                    suggestion=correct,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'疑似错别字：{desc}，建议改为「{correct}」',
                    rule_id='cn_typo'
                ))
        return issues

    def _check_english_spelling(self, text: str) -> List[Issue]:
        """英文拼写错误检测"""
        issues = []
        for match in self._en_typo_pattern.finditer(text):
            word = match.group()
            correct = self._en_typo_map.get(word.lower())
            if correct:
                # 保持原大小写
                if word[0].isupper():
                    correct = correct[0].upper() + correct[1:]
                issues.append(Issue(
                    type='typo',
                    severity='error',
                    original=word,
                    suggestion=correct,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'英文拼写可能有误，建议改为「{correct}」',
                    rule_id='en_spelling'
                ))
        return issues

    def _check_punctuation(self, text: str) -> List[Issue]:
        """标点符号问题检测"""
        issues = []
        tech = self._build_technical_skip_mask(text)

        # 1. 连续重复标点
        repeat_punct = re.compile(r'([，。！？；：、])\1+')
        for match in repeat_punct.finditer(text):
            issues.append(Issue(
                type='punctuation',
                severity='warning',
                original=match.group(),
                suggestion=match.group()[0],
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description='连续重复标点符号，建议仅保留一个',
                rule_id='repeat_punct'
            ))

        # 英文连续标点
        repeat_en_punct = re.compile(r'([.!?,;:])\1{2,}')
        for match in repeat_en_punct.finditer(text):
            issues.append(Issue(
                type='punctuation',
                severity='warning',
                original=match.group(),
                suggestion=match.group()[0],
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description='连续重复标点符号，建议精简',
                rule_id='repeat_punct_en'
            ))

        # 2. 中英文标点混用（在中文上下文中使用英文标点）
        # 检测：中文字符旁边的英文逗号、句号等
        mixed_punct = re.compile(r'([\u4e00-\u9fa5])([,;:!?])')
        for match in mixed_punct.finditer(text):
            punct_pos = match.start(2)
            if tech[punct_pos]:
                continue
            # 额外降噪：若半角标点后紧跟英文/数字/技术符号（如"标准：IEC/EN 60601-1: General"），
            # 且后续一小段内无其他汉字，则属于中英混排的技术内容，不强制改为中文标点。
            after_pos = match.end(2)
            window_end = min(after_pos + 30, len(text))
            after_window = text[after_pos:window_end]
            if re.match(r'[ \t]*[A-Za-z0-9]', after_window) and not re.search(r'[\u4e00-\u9fa5]', after_window):
                continue
            en_punct = match.group(2)
            cn_punct = {',': '，', ';': '；', ':': '：', '!': '！', '?': '？'}.get(en_punct, en_punct)
            issues.append(Issue(
                type='punctuation',
                severity='warning',
                original=en_punct,
                suggestion=cn_punct,
                position=punct_pos,
                end_position=match.end(2),
                context=self._get_context(text, match.start(), match.end()),
                description=f'中文语境中使用了英文标点「{en_punct}」，建议改为中文标点「{cn_punct}」',
                rule_id='mixed_punct'
            ))

        return issues

    def _build_delim_skip_mask(self, text: str) -> List[bool]:
        """构建"跳过掩码"：位于成对分隔符（书名号/括号/引号等）内部的位置为 True。

        书名《》、括号（）、方括号【】、直角引号「」『』以及半角()[]内部常出现空格
        （如《Harry Potter》（详见 附录 A）），这些空格通常不算错误，应跳过空格检查。
        """
        openers = '《（【「『(['
        closers = '》）】」』)]'
        open_to_close = dict(zip(openers, closers))
        close_set = set(closers)
        mask = [False] * len(text)
        stack = []
        for i, ch in enumerate(text):
            if ch in open_to_close:
                stack.append(ch)
            elif ch in close_set:
                if stack and open_to_close.get(stack[-1]) == ch:
                    stack.pop()
            if stack:
                mask[i] = True
        return mask

    def _build_technical_skip_mask(self, text: str) -> List[bool]:
        """构建"技术/英文内容跳过掩码"。
        标准引用行（如 IEC/EN 60601-1 | Medical...）、型号/版本列表、URL/邮箱等
        属于英文/技术排版，其内部半角标点与空格（含对齐空格）不应按中文规则检查。
        """
        mask = [False] * len(text)

        # 1. 标准/规范引用行：IEC/EN 60601-1 | ... 或 ISO 9001: ... 等
        std_ref = re.compile(
            r'^[ \t]*[A-Z]{2,}(?:/[A-Z]{2,})?\s*\d+(?:[-–—]\d+)*\s*[|:][ \t]*[A-Za-z]',
            re.MULTILINE
        )
        # 2. 型号/版本/日期列表行：含 | 且以字母数字/斜杠/连字符/点号开头
        model_line = re.compile(
            r'^[ \t]*[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+.*\|',
            re.MULTILINE
        )
        # 3. URL / 邮箱
        url_email = re.compile(r'https?://\S+|www\.\S+|\S+@\S+\.\S+')

        for pattern in (std_ref, model_line):
            for m in pattern.finditer(text):
                line_start = text.rfind('\n', 0, m.start()) + 1
                line_end = text.find('\n', m.end())
                if line_end == -1:
                    line_end = len(text)
                for i in range(line_start, line_end):
                    mask[i] = True

        for m in url_email.finditer(text):
            for i in range(m.start(), m.end()):
                mask[i] = True

        return mask

    def _check_spacing(self, text: str) -> List[Issue]:
        """空格和格式问题检测"""
        issues = []
        skip = self._build_delim_skip_mask(text)

        # 1. 中英文之间缺少空格
        missing_space = re.compile(r'([\u4e00-\u9fa5])([a-zA-Z0-9])')
        for match in missing_space.finditer(text):
            if skip[match.start()]:
                continue
            issues.append(Issue(
                type='spacing',
                severity='info',
                original=match.group(),
                suggestion=match.group(1) + ' ' + match.group(2),
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description='中文与英文/数字之间建议添加空格，提升可读性',
                rule_id='missing_space_cn_en'
            ))

        missing_space_rev = re.compile(r'([a-zA-Z0-9])([\u4e00-\u9fa5])')
        for match in missing_space_rev.finditer(text):
            if skip[match.start()]:
                continue
            issues.append(Issue(
                type='spacing',
                severity='info',
                original=match.group(),
                suggestion=match.group(1) + ' ' + match.group(2),
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description='英文/数字与中文之间建议添加空格，提升可读性',
                rule_id='missing_space_cn_en'
            ))

        # 2. 连续多个空格
        multi_space = re.compile(r'  +')
        for match in multi_space.finditer(text):
            if skip[match.start()]:
                continue
            # 跳过行首缩进
            line_start = text.rfind('\n', 0, match.start())
            if match.start() == line_start + 1:
                continue
            issues.append(Issue(
                type='spacing',
                severity='info',
                original=match.group(),
                suggestion=' ',
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description='存在连续多个空格，建议精简为一个',
                rule_id='multi_space'
            ))

        # 3. 行首/行尾多余空格
        lines = text.split('\n')
        offset = 0
        for line in lines:
            if line != line.strip() and line.strip():
                leading = len(line) - len(line.lstrip())
                trailing = len(line) - len(line.rstrip())
                if leading > 0:
                    issues.append(Issue(
                        type='spacing',
                        severity='info',
                        original=line[:leading],
                        suggestion='',
                        position=offset,
                        end_position=offset + leading,
                        context=self._get_context(text, offset, offset + leading),
                        description='行首有多余空格',
                        rule_id='leading_space'
                    ))
                if trailing > 0:
                    issues.append(Issue(
                        type='spacing',
                        severity='info',
                        original=line[-trailing:],
                        suggestion='',
                        position=offset + len(line) - trailing,
                        end_position=offset + len(line),
                        context=self._get_context(text, offset + len(line) - trailing, offset + len(line)),
                        description='行尾有多余空格',
                        rule_id='trailing_space'
                    ))
            offset += len(line) + 1

        # 4. 连续多个空行
        multi_blank = re.compile(r'\n{3,}')
        for match in multi_blank.finditer(text):
            issues.append(Issue(
                type='spacing',
                severity='info',
                original=match.group(),
                suggestion='\n\n',
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description='存在连续多个空行，建议精简',
                rule_id='multi_blank_line'
            ))

        return issues

    def _check_repeated_words(self, text: str) -> List[Issue]:
        """重复词语检测"""
        issues = []

        # 1. 中文连续重复词（2字及以上）
        repeat_cn = re.compile(r'([\u4e00-\u9fa5]{2,4})\1')
        for match in repeat_cn.finditer(text):
            word = match.group(1)
            if word not in REPEAT_STOPWORDS and len(word) >= 2:
                issues.append(Issue(
                    type='repetition',
                    severity='warning',
                    original=match.group(),
                    suggestion=word,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'词语「{word}」连续重复，可能为笔误',
                    rule_id='repeat_word_cn'
                ))

        # 2. 单字重复（3次及以上，排除语气词）
        tone_words = {'啊', '呀', '哦', '哎', '唉', '嗯', '哈', '嘛', '吧', '呢', '啦', '哟'}
        repeat_char = re.compile(r'([\u4e00-\u9fa5])\1{2,}')
        for match in repeat_char.finditer(text):
            char = match.group(1)
            if char not in tone_words:
                issues.append(Issue(
                    type='repetition',
                    severity='warning',
                    original=match.group(),
                    suggestion=char * 2,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'字「{char}」连续重复{len(match.group())}次，可能为笔误',
                    rule_id='repeat_char_cn'
                ))

        # 3. 英文连续重复单词
        repeat_en = re.compile(r'(?<![a-zA-Z])([a-zA-Z]+)\s+\1(?![a-zA-Z])', re.IGNORECASE)
        for match in repeat_en.finditer(text):
            word = match.group(1)
            # 排除合法重复（如 "had had", "that that" 在特定语法结构中）
            if word.lower() not in {'had', 'that', 'is', 'was'}:
                issues.append(Issue(
                    type='repetition',
                    severity='warning',
                    original=match.group(),
                    suggestion=word,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'英文单词「{word}」连续重复，可能为笔误',
                    rule_id='repeat_word_en'
                ))

        return issues

    def _check_long_sentences(self, text: str) -> List[Issue]:
        """长句检测"""
        issues = []

        # 按中文句末标点分句
        sentence_pattern = re.compile(r'[^。！？\n]+[。！？]')
        for match in sentence_pattern.finditer(text):
            sentence = match.group()
            # 计算中文字符数
            cn_chars = len(re.findall(r'[\u4e00-\u9fa5]', sentence))
            if cn_chars > 80:
                issues.append(Issue(
                    type='style',
                    severity='info',
                    original=sentence[:30] + '...' if len(sentence) > 30 else sentence,
                    suggestion='（建议拆分为多个短句）',
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'此句较长（约{cn_chars}字），长句可能影响理解，建议适当拆分',
                    rule_id='long_sentence_cn'
                ))

        # 英文长句检测（按句号分句）
        en_sentence_pattern = re.compile(r'[A-Za-z][^.!?\n]+[.!?]')
        for match in en_sentence_pattern.finditer(text):
            sentence = match.group()
            word_count = len(sentence.split())
            if word_count > 40:
                issues.append(Issue(
                    type='style',
                    severity='info',
                    original=sentence[:40] + '...' if len(sentence) > 40 else sentence,
                    suggestion='（建议拆分为多个短句）',
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'此英文句子较长（约{word_count}词），建议适当拆分以提升可读性',
                    rule_id='long_sentence_en'
                ))

        return issues

    def _check_brackets_quotes(self, text: str) -> List[Issue]:
        """括号和引号配对检测（按段落/行局部检查，降低误报）"""
        issues = []

        # 开括号到闭括号的映射（区分半角/全角）
        half_open_to_close = {'(': ')', '[': ']', '<': '>'}
        full_open_to_close = {'（': '）', '【': '】', '《': '》'}
        all_open_to_close = {**half_open_to_close, **full_open_to_close}
        # 统一按半角处理内部逻辑
        open_chars = set('([<')
        close_chars = set(')]>')
        norm_open_to_close = {'(': ')', '[': ']', '<': '>'}
        # 全角 -> 半角映射，用于统一入栈比较
        normalize = {'（': '(', '）': ')', '【': '[', '】': ']', '《': '<', '》': '>'}

        # 常见编号/列表前缀正则，用于忽略合法单字符括号
        numbering_pattern = re.compile(r'^[\s]*[(（][\d一二三四五六七八九十零〇a-zA-Z]+[)）][\s]*')

        def check_scope(scope_text: str, base_offset: int):
            """检查一个作用域（段落/行）内的括号匹配"""
            scope_issues = []

            # 1. 检测混用括号（如 (内容） 或 （内容)）
            # 扫描每个开括号，看是否被不同宽度的闭括号关闭
            mixed_pattern = re.compile(r'[(（]([^()（）【】\[\]<>《》]*?)[)）]')
            for m in mixed_pattern.finditer(scope_text):
                open_ch = m.group(0)[0]
                close_ch = m.group(0)[-1]
                if (open_ch in '([<' and close_ch not in ')]>') or \
                   (open_ch in '（【《' and close_ch not in '）】》'):
                    scope_issues.append(Issue(
                        type='punctuation',
                        severity='warning',
                        original=m.group(0),
                        suggestion=f'{open_ch}{m.group(1)}{all_open_to_close[open_ch]}',
                        position=base_offset + m.start(),
                        end_position=base_offset + m.end(),
                        context=self._get_context(text, base_offset + m.start(), base_offset + m.end()),
                        description=f'括号混用：「{open_ch}」与「{close_ch}」宽度不一致，建议统一',
                        rule_id='mixed_width_bracket'
                    ))

            # 2. 使用栈检测未配对括号
            stack = []  # 元素: (normalized_open_char, absolute_position, original_char)
            for i, ch in enumerate(scope_text):
                norm = normalize.get(ch, ch)
                if norm in open_chars:
                    stack.append((norm, base_offset + i, ch))
                elif norm in close_chars:
                    if stack and norm_open_to_close.get(stack[-1][0]) == norm:
                        stack.pop()
                    else:
                        # 闭括号没有对应开括号（可能是跨行/跨段合法，这里先不报错，由后面兜底）
                        pass

            # 栈中剩余的就是未配对的开括号
            for _, pos, orig in stack:
                norm = normalize.get(orig, orig)
                correct_close = norm_open_to_close.get(norm, '')
                scope_issues.append(Issue(
                    type='punctuation',
                    severity='warning',
                    original=orig,
                    suggestion=orig + correct_close if correct_close else orig,
                    position=pos,
                    end_position=pos + 1,
                    context=self._get_context(text, pos, pos + 1),
                    description=f'「{orig}」在当前段落中缺少对应的闭括号「{correct_close}」，请检查是否遗漏',
                    rule_id='unmatched_bracket'
                ))

            return scope_issues

        # 按行/段落切分作用域
        lines = text.split('\n')
        offset = 0
        for line in lines:
            # 跳过纯编号行（如 "(2)" 单独一行）和空行
            stripped = line.strip()
            if not stripped:
                offset += len(line) + 1
                continue
            if numbering_pattern.match(stripped) and len(stripped) <= 8:
                offset += len(line) + 1
                continue
            issues.extend(check_scope(line, offset))
            offset += len(line) + 1

        # 中文引号配对：按行统计，数量不匹配才提示（不报具体位置）
        for open_q, close_q in [('"', '"'), ('「', '」'), ('『', '』')]:
            total_open = text.count(open_q)
            total_close = text.count(close_q)
            if total_open != total_close:
                issues.append(Issue(
                    type='punctuation',
                    severity='warning',
                    original=open_q + close_q,
                    suggestion=open_q + close_q,
                    position=0,
                    end_position=0,
                    context='',
                    description=f'引号「{open_q}{close_q}」数量不匹配（左{total_open}个，右{total_close}个），请检查是否遗漏',
                    rule_id='unmatched_quote'
                ))

        return issues

    def _check_extra_spaces(self, text: str) -> List[Issue]:
        """多余空格检测"""
        issues = []
        skip = self._build_delim_skip_mask(text)
        tech = self._build_technical_skip_mask(text)

        # 分词式排版判定：若自由文本普遍以"空格"分隔中文词（如"我们 今天 去 公园"、
        # "本 公 司 成 立"，常见于宣传文案/字幕/OCR 稿），则空格是有意排版，
        # 不应逐处报"多余空格"。仅当空格是零散出现（密度低）时才视为真正多余。
        # 计算密度时忽略书名号/括号内部（其内部空格本就不报），避免被内部排版干扰。
        cn_space_cn = re.compile(r'([\u4e00-\u9fa5])( +)([\u4e00-\u9fa5])')
        seg_matches = list(cn_space_cn.finditer(text))
        seg_count = 0
        cn_pair_count = 0
        n = len(text)
        for i in range(n - 1):
            if skip[i] or skip[i + 1]:
                continue
            a, b = text[i], text[i + 1]
            if '\u4e00' <= a <= '\u9fa5' and '\u4e00' <= b <= '\u9fa5':
                cn_pair_count += 1
            elif '\u4e00' <= a <= '\u9fa5' and b == ' ' and i + 2 < n and '\u4e00' <= text[i + 2] <= '\u9fa5':
                seg_count += 1
        # 空格分隔的相邻汉字对 占 全部相邻汉字对 的比例
        total_pairs = seg_count + cn_pair_count
        # 判定为"分词式有意排版"的两种情形：
        #  - 连续分词空格较多（>=3 处）；或
        #  - 空格密度很高（>=0.5，即相邻汉字对大多以空格分隔，如整篇逐字空格）
        # 仅当空格零散出现（不满足上述）时才视为真正多余、照常报。
        segmented_style = seg_count >= 3 or (total_pairs > 0 and (seg_count / total_pairs) >= 0.5)

        # 1. 中文字符之间的多余空格（如"翻 译"应为"翻译"）
        for match in seg_matches:
            if skip[match.start()]:
                continue
            if segmented_style:
                continue
            issues.append(Issue(
                type='spacing',
                severity='error',
                original=match.group(),
                suggestion=match.group(1) + match.group(3),
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description=f'中文字符之间存在多余空格，建议删除',
                rule_id='cn_extra_space'
            ))

        # 2. 连续多个空格（非行首，2个及以上）
        multi_space = re.compile(r'(?<=\S)( {2,})')
        for match in multi_space.finditer(text):
            if skip[match.start()]:
                continue
            if tech[match.start()]:
                continue
            issues.append(Issue(
                type='spacing',
                severity='warning',
                original=match.group(),
                suggestion=' ',
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description='存在连续多个空格，建议精简为一个',
                rule_id='multi_space'
            ))

        # 3. 中文标点前的多余空格（如"你好 ，"应为"你好，"）
        space_before_punct = re.compile(r'( +)([，。！？；：、）】》」』])')
        for match in space_before_punct.finditer(text):
            if skip[match.start()]:
                continue
            if segmented_style:
                continue
            issues.append(Issue(
                type='spacing',
                severity='error',
                original=match.group(),
                suggestion=match.group(2),
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description=f'标点符号「{match.group(2)}」前有多余空格，建议删除',
                rule_id='space_before_punct'
            ))

        # 4. 括号/引号内部首尾的多余空格（如"（ 内容 ）"应为"（内容）"）
        space_in_bracket = re.compile(r'([（【《「『(]) +([^\s])')
        for match in space_in_bracket.finditer(text):
            if skip[match.start()]:
                continue
            if segmented_style:
                continue
            issues.append(Issue(
                type='spacing',
                severity='warning',
                original=match.group(),
                suggestion=match.group(1) + match.group(2),
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description=f'「{match.group(1)}」后有多余空格，建议删除',
                rule_id='space_after_open_bracket'
            ))

        space_in_bracket2 = re.compile(r'([^\s]) +([）】》」』)])')
        for match in space_in_bracket2.finditer(text):
            if skip[match.start()]:
                continue
            if segmented_style:
                continue
            issues.append(Issue(
                type='spacing',
                severity='warning',
                original=match.group(),
                suggestion=match.group(1) + match.group(2),
                position=match.start(),
                end_position=match.end(),
                context=self._get_context(text, match.start(), match.end()),
                description=f'「{match.group(2)}」前有多余空格，建议删除',
                rule_id='space_before_close_bracket'
            ))

        return issues

    @staticmethod
    def _is_only_determiner_use(sentence: str, only_pos: int) -> bool:
        """判断「只有」在句中是否为限定副词用法（如：只有一次、只有部分），
        而非「只有……才」条件关联词。"""
        if only_pos + 2 >= len(sentence):
            return False
        after = sentence[only_pos + 2:]
        # 只取到下一个主要标点前的片段
        seg = re.split(r'[，。！？；]', after)[0].strip()
        if not seg:
            return False
        # 数量表达：数字/中文数字 + 可选量词；或「几/这/那/此/部分/少数」等限定词
        return bool(re.match(
            r'(?:[一二三四五六七八九十百千万零几两\d]+'
            r'(?:个|次|只|种|项|条|位|份|件|倍|回|年|月|日|分|秒)?'
            r'|几(?:个|次|只|种|项|条|位|份|件)?'
            r'|[这那此](?:个|次|只|种|项|条|位|份|些)?'
            r'|[部少多所全一](?:分|些|数)'
            r'|所有|全部|一切)',
            seg
        ))

    def _check_missing_chars(self, text: str) -> List[Issue]:
        """漏字检测"""
        issues = []

        # 1. 常见固定搭配缺字（如"迫不及"缺少"待"）
        incomplete_items = [(k, v) for k, v in INCOMPLETE_PHRASES.items() if v is not None]
        incomplete_items.sort(key=lambda x: len(x[0]), reverse=True)
        if incomplete_items:
            incomplete_pattern = re.compile(
                '(' + '|'.join(re.escape(k) for k, _ in incomplete_items) + r')(?![\u4e00-\u9fa5])'
            )
            incomplete_map = {k: v for k, v in incomplete_items}
            for match in incomplete_pattern.finditer(text):
                fragment = match.group()
                if fragment in incomplete_map:
                    full, desc = incomplete_map[fragment]
                    issues.append(Issue(
                        type='missing_char',
                        severity='error',
                        original=fragment,
                        suggestion=full,
                        position=match.start(),
                        end_position=match.end(),
                        context=self._get_context(text, match.start(), match.end()),
                        description=f'疑似漏字：{desc}，建议补全为「{full}」',
                        rule_id='incomplete_phrase'
                    ))

        # 2. 关联词配对缺失检测
        # 按句分割（中文句末标点）
        sentences = re.split(r'[。！？\n]', text)
        sentence_offsets = []
        offset = 0
        for sep_match in re.finditer(r'[。！？\n]', text):
            sentence_offsets.append((offset, sep_match.start()))
            offset = sep_match.end()
        sentence_offsets.append((offset, len(text)))

        for first_part, second_parts, pair_desc in PAIRED_CONJUNCTIONS:
            for sent_start, sent_end in sentence_offsets:
                sentence = text[sent_start:sent_end]
                if first_part in sentence:
                    # 检查同句中是否有配对的后半句
                    found_second = any(sp in sentence for sp in second_parts)
                    if not found_second:
                        # 扩大范围：检查后续1个句子
                        next_end = min(sent_end + 50, len(text))
                        extended = text[sent_start:next_end]
                        found_second_ext = any(sp in extended for sp in second_parts)
                        if not found_second_ext:
                            pos = sentence.find(first_part) + sent_start
                            # 降噪：「只有」的限定副词用法（如「只有一次」「只有部分」）
                            # 不强制要求「才」
                            if first_part == '只有' and self._is_only_determiner_use(sentence, pos - sent_start):
                                continue
                            # suggestion 使用描述性文本，前端会识别为不可直接替换的提示
                            issues.append(Issue(
                                type='missing_char',
                                severity='warning',
                                original=first_part,
                                suggestion=f'（建议补全关联词：{pair_desc}）',
                                position=pos,
                                end_position=pos + len(first_part),
                                context=self._get_context(text, pos, pos + len(first_part)),
                                description=f'关联词「{first_part}」出现但未找到配对的「{'/'.join(second_parts[:2])}」，可能遗漏后半句',
                                rule_id='missing_conjunction_pair'
                            ))

        # 3. 常见搭配中的缺字模式
        # "由于...原因" → 可能缺"的"（"由于...的原因"）
        # "为了...目的" → 可能缺"的"
        # "在...过程中" → 检查完整性
        missing_particle_patterns = [
            (re.compile(r'由于([^，。！？\n]{2,20})原因'), '由于……的原因', '由于', '由于……的原因'),
            (re.compile(r'为了([^，。！？\n]{2,20})目的'), '为了……的目的', '为了', '为了……的目的'),
        ]
        for pattern, full_form, keyword, desc in missing_particle_patterns:
            for match in pattern.finditer(text):
                content = match.group(1)
                # 检查是否已有"的"
                if not content.endswith('的'):
                    issues.append(Issue(
                        type='missing_char',
                        severity='warning',
                        original=match.group(),
                        suggestion=match.group().replace(content + '原因', content + '的原因').replace(content + '目的', content + '的目的'),
                        position=match.start(),
                        end_position=match.end(),
                        context=self._get_context(text, match.start(), match.end()),
                        description=f'「{desc}」中可能缺少「的」字',
                        rule_id='missing_particle'
                    ))

        return issues

    def _make_expression_issue(self, text, match, replacements, desc, rule_id, severity='warning'):
        """生成带改写候选的表达问题 Issue

        replacements: 替换模板列表，第一个为默认建议，全部去重后作为 alternatives。
        """
        alts = []
        seen = set()
        for tmpl in replacements:
            expanded = match.expand(tmpl)
            if expanded not in seen:
                seen.add(expanded)
                alts.append(expanded)
        return Issue(
            type='expression',
            severity=severity,
            original=match.group(),
            suggestion=alts[0],
            position=match.start(),
            end_position=match.end(),
            context=self._get_context(text, match.start(), match.end()),
            description=desc,
            rule_id=rule_id,
            alternatives=alts if len(alts) > 1 else None
        )

    def _check_expression_issues(self, text: str) -> List[Issue]:
        """语病和表达问题检测"""
        issues = []

        # ============================================================
        # 1. 句式杂糅：两种句式混合在一起
        # 每条规则提供 2 个改写方案，对应两种各自的正确句式
        # ============================================================
        mixing_rules = [
            (r'原因是([^\n，。！？]{2,30})造成的',
             [r'原因是\1', r'是由\1造成的'],
             '句式杂糅：「原因是…造成的」混合了「原因是…」和「由…造成的」两种句式'),
            (r'是为了([^\n，。！？]{2,30})为目的',
             [r'是为了\1', r'是以\1为目的'],
             '句式杂糅：「是为了…为目的」混合了「是为了…」和「以…为目的」两种句式'),
            (r'本着([^\n，。！？]{2,20})为原则',
             [r'本着\1原则', r'以\1为原则'],
             '句式杂糅：「本着…为原则」混合了「本着…原则」和「以…为原则」两种句式'),
            (r'靠的是([^\n，。！？]{2,20})取得的',
             [r'靠的是\1', r'是靠\1取得的'],
             '句式杂糅：「靠的是…取得的」混合了两种句式'),
            (r'围绕以([^\n，。！？]{2,20})为中心',
             [r'围绕\1', r'以\1为中心'],
             '句式杂糅：「围绕以…为中心」混合了「围绕…」和「以…为中心」两种句式'),
            (r'关键在于([^\n，。！？]{2,20})起决定作用',
             [r'关键在于\1', r'\1起决定作用'],
             '句式杂糅：「关键在于…起决定作用」混合了两种句式'),
            (r'目的是为了([^\n，。！？]{2,30})',
             [r'目的是\1', r'为了\1'],
             '语义重复：「目的」与「为了」含义重叠，建议保留其一'),
        ]
        for pattern, replacements, desc in mixing_rules:
            for match in re.finditer(pattern, text):
                issues.append(self._make_expression_issue(
                    text, match, replacements, desc, 'sentence_mixing'))

        # ============================================================
        # 2. 成分赘余：语义重复的多余词语
        # 提供两种删减方案（删前半或删后半）
        # ============================================================
        redundancy_rules = [
            (r'大约([\u4e00-\u9fa5\d]{1,15})左右',
             [r'大约\1', r'\1左右'],
             '语义重复：「大约」与「左右」均表示约数，建议删去其一'),
            (r'大约([\u4e00-\u9fa5\d]{1,15})上下',
             [r'大约\1', r'\1上下'],
             '语义重复：「大约」与「上下」均表示约数，建议删去其一'),
            (r'超过([\u4e00-\u9fa5\d]{1,15})以上',
             [r'超过\1', r'\1以上'],
             '语义重复：「超过」已含「以上」之意，建议删去其一'),
            (r'近([\d]{1,10})左右',
             [r'近\1', r'\1左右'],
             '语义重复：「近」已含约数之意，建议删去其一'),
            (r'来自于',
             [r'来自', r'出自'],
             '成分赘余：「来自」已含方向义，无需加「于」'),
            (r'这其中',
             [r'其中', r'这里面'],
             '成分赘余：「这」与「其中」含义重叠，建议用「其中」'),
            (r'共计总数',
             [r'共计', r'总数'],
             '语义重复：「共计」与「总数」含义重叠'),
            (r'最后的结局',
             [r'结局', r'最终结局'],
             '语义重复：「结局」已含最后之意'),
            (r'初衷的本意',
             [r'初衷', r'本意'],
             '语义重复：「初衷」即本来的意思'),
            (r'众多的人们',
             [r'众多的人', r'众人'],
             '成分赘余：「人们」中的「们」表复数，与「众多」重叠'),
            (r'互相彼此',
             [r'彼此', r'互相'],
             '语义重复：「互相」与「彼此」含义相同'),
            (r'第一个首先',
             [r'首先', r'第一'],
             '语义重复：「第一个」与「首先」含义重叠'),
            (r'开始起步',
             [r'起步', r'开始'],
             '语义重复：「开始」与「起步」含义重叠'),
        ]
        for pattern, replacements, desc in redundancy_rules:
            for match in re.finditer(pattern, text):
                issues.append(self._make_expression_issue(
                    text, match, replacements, desc, 'redundancy'))

        # ============================================================
        # 3. 搭配不当：动词与宾语搭配错误
        # 方案1：换动词；方案2：换宾语/删多余成分
        # ============================================================
        collocation_rules = [
            (r'改善([\u4e00-\u9fa5]{1,6})水平',
             [r'提高\1水平', r'改善\1'],
             '搭配不当：「改善」不宜搭配「水平」，建议改为「提高…水平」或删去「水平」'),
            (r'增加([\u4e00-\u9fa5]{1,6})意识',
             [r'增强\1意识', r'提高\1意识'],
             '搭配不当：「增加」不宜搭配「意识」，建议改为「增强…意识」'),
            (r'扩大([\u4e00-\u9fa5]{1,6})能力',
             [r'提高\1能力', r'增强\1能力'],
             '搭配不当：「扩大」不宜搭配「能力」，建议改为「提高…能力」'),
            (r'改善([\u4e00-\u9fa5]{1,6})效率',
             [r'提高\1效率', r'改善\1'],
             '搭配不当：「改善」不宜搭配「效率」，建议改为「提高…效率」'),
        ]
        for pattern, replacements, desc in collocation_rules:
            for match in re.finditer(pattern, text):
                issues.append(self._make_expression_issue(
                    text, match, replacements, desc, 'collocation_error'))

        # ============================================================
        # 4. 不合逻辑：双重否定导致表意相反
        # 方案1：删去否定词（保持原意）；方案2：改动词（反转句意）
        # ============================================================
        illogic_rules = [
            (r'防止([^\n，。！？]{1,20})不再',
             [r'防止\1', r'确保\1不再'],
             '不合逻辑：「防止…不再」双重否定导致表意相反'),
            (r'避免([^\n，。！？]{1,20})不再',
             [r'避免\1', r'确保\1不再'],
             '不合逻辑：「避免…不再」双重否定导致表意相反'),
            (r'阻止([^\n，。！？]{1,20})不再',
             [r'阻止\1', r'确保\1不再'],
             '不合逻辑：「阻止…不再」双重否定导致表意相反'),
            (r'切忌不要([^\n，。！？]{1,15})',
             [r'切忌\1', r'切勿\1'],
             '不合逻辑：「切忌」已含否定义，与「不要」构成双重否定'),
        ]
        for pattern, replacements, desc in illogic_rules:
            for match in re.finditer(pattern, text):
                issues.append(self._make_expression_issue(
                    text, match, replacements, desc, 'illogic_double_neg', severity='error'))

        # ============================================================
        # 5. 成分残缺：通过…使… 导致主语缺失
        # 方案1：去掉"使"并断句；方案2：去掉介词让"使"做谓语
        # ============================================================
        missing_subject_rules = [
            (r'通过([^\n，。！？]{2,30})使',
             [r'通过\1，', r'\1使'],
             '成分残缺：「通过…使…」句式吞没了主语，建议断句或去掉「通过」'),
            (r'经过([^\n，。！？]{2,30})使',
             [r'经过\1，', r'\1使'],
             '成分残缺：「经过…使…」句式吞没了主语，建议断句或去掉「经过」'),
            (r'由于([^\n，。！？]{2,30})使',
             [r'由于\1，', r'\1使'],
             '成分残缺：「由于…使…」句式吞没了主语，建议断句或去掉「由于」'),
        ]
        for pattern, replacements, desc in missing_subject_rules:
            for match in re.finditer(pattern, text):
                issues.append(self._make_expression_issue(
                    text, match, replacements, desc, 'missing_subject'))

        # ============================================================
        # 6. 的/地/得 误用（常见搭配）
        # 方案1：改"的"为"地"；方案2：去掉"的/地"直接修饰
        # ============================================================
        _verbs = r'说|写|走|跑|吃|看|听|想|讲|唱|跳|笑|哭|叫|喊|打|踢|学|做|干|玩|问|答|读|记|算|考|试|工|作|完|成|备|建|改|修|制|定|出|发|展|进|行|用|帮|让|到|得|了|过|去|来|给|带|找|买|卖|送|放|拿|站|坐|睡|醒|死|活|生|长|变|动|停|开|关|推|拉|提|举|放|落|升|降|破|立|建|拆|搬|运|选|挑|换|穿|脱|洗|擦|扫|切|割|剪|缝|编|织|种|养|喂|捕|钓|猎'
        de_di_patterns = [
            (rf'认真的([一-龥]{{0,4}}(?:{_verbs}))',
             [r'认真地\1', r'认真\1'],
             '「的」后接动词作状语时，应使用「地」或省略'),
            (rf'仔细的([一-龥]{{0,4}}(?:{_verbs}))',
             [r'仔细地\1', r'仔细\1'],
             '「的」后接动词作状语时，应使用「地」或省略'),
            (rf'慢慢的([一-龥]{{0,4}}(?:{_verbs}))',
             [r'慢慢地\1', r'慢慢\1'],
             '「的」后接动词作状语时，应使用「地」或省略'),
            (rf'努力的([一-龥]{{0,4}}(?:{_verbs}))',
             [r'努力地\1', r'努力\1'],
             '「的」后接动词作状语时，应使用「地」或省略'),
            (rf'积极的([一-龥]{{0,4}}(?:{_verbs}))',
             [r'积极地\1', r'积极\1'],
             '「的」后接动词作状语时，应使用「地」或省略'),
        ]
        for pattern, replacements, desc in de_di_patterns:
            for match in re.finditer(pattern, text):
                issues.append(self._make_expression_issue(
                    text, match, replacements, desc, 'de_vs_di'))

        return issues

    def _find_de_redundancies(self, sentence: str):
        """在单句内定位"的"字冗余区间。

        只在确实存在冗余时才返回结果，避免对正常的"的"散用误报：
          - 连续"的的"：明显冗余；
          - 以 10 个 CJK 字符为滑动窗口，窗内出现 >=3 个"的"，且其中至少存在一个
            可安全删除的"的"（位于"化/性/度"之后）。

        返回 [(start, end, removable_idxs), ...]，下标均为 sentence 内字符下标。
        """
        clusters = []
        de_positions = [i for i, ch in enumerate(sentence) if ch == '的']
        if len(de_positions) < 2:
            return clusters

        # 1. 连续"的的"：明显冗余，删除前一个"的"
        for m in re.finditer(r'的的', sentence):
            s, e = m.start(), m.end()
            cs = max(0, s - 2)
            ce = min(len(sentence), e + 2)
            clusters.append((cs, ce, [s]))

        # 2. 密集堆砌：仅当存在"可安全删除"的"的"时才视为冗余
        cn_chars = []  # (sentence_index, is_de)
        for i, ch in enumerate(sentence):
            if '\u4e00' <= ch <= '\u9fff' or ch == '的':
                cn_chars.append((i, ch == '的'))
        W = 10
        n = len(cn_chars)
        i = 0
        while i <= n - W:
            window = cn_chars[i:i + W]
            de_idxs = [cn_chars[i + k][0] for k in range(W) if window[k][1]]
            if len(de_idxs) >= 3:
                # 仅在"的"位于 化/性/度 之后时，删除才安全、不改变语义
                safe = [idx for idx in de_idxs if idx > 0 and sentence[idx - 1] in '化性度']
                if safe:
                    removable = safe[:1]  # 每次只删一个多余"的"
                    cs = max(0, cn_chars[i][0] - 1)
                    ce = min(len(sentence), cn_chars[i + W - 1][0] + 2)
                    clusters.append((cs, ce, removable))
                i += W  # 跳过该窗口，避免重复报告同一处
            else:
                i += 1
        return clusters

    def _check_grammar_patterns(self, text: str) -> List[Issue]:
        """语法模式检测（聚焦真正冗余/错误的"的"字用法，避免对正常散用过度报警）

        设计原则：正常散用的"的"不视为问题；只有确实存在冗余（连续"的的"或
        密集堆砌且可安全精简）时才报告，且 original/suggestion 精确到冗余片段，
        而不是整句重写——这样前端只需高亮被改动的那几个字。
        """
        issues = []

        # "的"字冗余检测
        sentence_pattern = re.compile(r'[^。！？\n]+[。！？]')
        for match in sentence_pattern.finditer(text):
            sentence = match.group()
            if sentence.count('的') < 2:
                continue
            base = match.start()
            for (cs, ce, removable) in self._find_de_redundancies(sentence):
                if not removable:
                    continue
                orig_seg = sentence[cs:ce]
                rm_set = set(removable)
                sugg_seg = ''.join(ch for j, ch in enumerate(orig_seg) if (cs + j) not in rm_set)
                if sugg_seg == orig_seg:
                    continue
                # 备选方案：分别删除不同冗余"的"
                alternatives = []
                seen = set()
                for rm in removable:
                    s = ''.join(ch for j, ch in enumerate(orig_seg) if (cs + j) != rm)
                    if s != orig_seg and s not in seen:
                        seen.add(s)
                        alternatives.append(s)
                issues.append(Issue(
                    type='grammar',
                    severity='info',
                    original=orig_seg,
                    suggestion=sugg_seg,
                    position=base + cs,
                    end_position=base + ce,
                    context=self._get_context(text, base + cs, base + ce),
                    description='此处的"的"字使用冗余，建议删去以精简语句',
                    rule_id='redundant_de',
                    alternatives=alternatives if len(alternatives) > 1 else None
                ))

        return issues

    def _check_variant_chars(self, text: str) -> List[Issue]:
        """异形词检测：推荐使用规范词形"""
        issues = []
        # 构建 非推荐词 -> (推荐词, 说明) 的映射
        variant_map = {}
        for recommended, (non_recommended, desc) in VARIANT_WORDS.items():
            if desc is None:
                continue
            variant_map[non_recommended] = (recommended, desc)

        if not variant_map:
            return issues

        items = sorted(variant_map.items(), key=lambda x: len(x[0]), reverse=True)
        pattern = re.compile('|'.join(re.escape(k) for k, _ in items))

        for match in pattern.finditer(text):
            word = match.group()
            if word in variant_map:
                recommended, desc = variant_map[word]
                issues.append(Issue(
                    type='variant_char',
                    severity='warning',
                    original=word,
                    suggestion=recommended,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'异形词：{desc}，建议改为「{recommended}」',
                    rule_id='variant_word'
                ))

        # 2. 异形/不规范单字检测（部首字形、异体字形等）
        for idx, ch in enumerate(text):
            if ch in IRREGULAR_CHARS:
                std_ch, desc = IRREGULAR_CHARS[ch]
                issues.append(Issue(
                    type='variant_char',
                    severity='error',
                    original=ch,
                    suggestion=std_ch,
                    position=idx,
                    end_position=idx + 1,
                    context=self._get_context(text, idx, idx + 1),
                    description=f'异形字：{desc}',
                    rule_id='irregular_char'
                ))
        return issues

    def _check_half_full_width(self, text: str) -> List[Issue]:
        """全角/半角标点混用检测"""
        issues = []

        # 1. 中文字符之间使用了半角标点（应使用全角）
        cn_context_half = re.compile(r'([\u4e00-\u9fa5])([,;:!?])')
        for match in cn_context_half.finditer(text):
            half = match.group(2)
            full = HALF_FULL_PUNCT.get(half, half)
            issues.append(Issue(
                type='width_mixed',
                severity='warning',
                original=half,
                suggestion=full,
                position=match.start(2),
                end_position=match.end(2),
                context=self._get_context(text, match.start(), match.end()),
                description=f'中文语境中使用了半角标点「{half}」，建议改为全角「{full}」',
                rule_id='half_in_cn_context'
            ))

        # 2. 中文字符后跟半角句号
        cn_half_period = re.compile(r'([\u4e00-\u9fa5])\.')
        for match in cn_half_period.finditer(text):
            # 排除数字小数点（如 3.14）
            before = text[:match.start()]
            if re.search(r'\d$', before):
                continue
            issues.append(Issue(
                type='width_mixed',
                severity='warning',
                original='.',
                suggestion='。',
                position=match.start(1) + 1,
                end_position=match.start(1) + 2,
                context=self._get_context(text, match.start(), match.end()),
                description='中文语境中使用了半角句号「.」，建议改为全角「。」',
                rule_id='half_period_in_cn'
            ))

        # 3. 混用括号（半角开括号配全角闭括号，或反之）
        mixed_brackets = re.compile(r'[\(（][^\(\)（）]*[\)）]')
        for match in mixed_brackets.finditer(text):
            open_ch = match.group()[0]
            close_ch = match.group()[-1]
            if (open_ch == '(' and close_ch == '）') or (open_ch == '（' and close_ch == ')'):
                correct_close = '）' if open_ch == '（' else ')'
                correct_open = '（' if close_ch == '）' else '('
                issues.append(Issue(
                    type='width_mixed',
                    severity='warning',
                    original=match.group(),
                    suggestion=open_ch + match.group()[1:-1] + correct_close if open_ch in '（【' else correct_open + match.group()[1:-1] + close_ch,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'括号全半角混用：「{open_ch}」与「{close_ch}」宽度不一致',
                    rule_id='mixed_width_paren'
                ))

        return issues

    def _check_idiom_misuse(self, text: str) -> List[Issue]:
        """成语误用检测：常见被误解或误用的成语"""
        issues = []
        for pattern_str, replacements, misuse_desc, correct_tip in IDIOM_MISUSE:
            for match in re.finditer(pattern_str, text):
                # 过滤 None 占位候选
                valid_alts = [a for a in replacements if a]
                primary = valid_alts[0] if valid_alts else match.group()
                issues.append(Issue(
                    type='idiom_misuse',
                    severity='info',
                    original=match.group(),
                    suggestion=primary,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'成语误用提醒：{misuse_desc}。{correct_tip}',
                    rule_id='idiom_misuse',
                    alternatives=valid_alts if len(valid_alts) > 1 else None
                ))
        return issues

    def _check_colloquial(self, text: str) -> List[Issue]:
        """口语化表达检测：正式文档中不宜使用的口语化词语"""
        issues = []
        for pattern_str, replacements, desc in COLLOQUIAL_EXPRESSIONS:
            for match in re.finditer(pattern_str, text):
                # 过滤掉 None 占位候选，确保至少保留有效候选
                valid_alts = [r for r in replacements if r]
                if not valid_alts:
                    valid_alts = [match.group()]
                primary = valid_alts[0]
                issues.append(Issue(
                    type='colloquial',
                    severity='info',
                    original=match.group(),
                    suggestion=primary,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'口语化表达：{desc}',
                    rule_id='colloquial_expr',
                    alternatives=valid_alts
                ))
        return issues

    def _check_custom_glossary(self, text: str, glossary: List[Dict]) -> List[Issue]:
        """自定义术语表检查：用户定义的「非规范写法 → 规范写法」对，
        在文本中检测非规范写法并提示替换为规范写法。"""
        issues = []
        for item in glossary:
            original = item.get('original', '').strip()
            standard = item.get('standard', '').strip()
            if not original or not standard or original == standard:
                continue
            # 用正则查找所有出现位置（注意转义特殊字符）
            try:
                pattern = re.compile(re.escape(original))
            except re.error:
                continue
            for match in pattern.finditer(text):
                issues.append(Issue(
                    type='custom_term',
                    severity='warning',
                    original=match.group(),
                    suggestion=standard,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'自定义术语：根据术语表，「{original}」应统一为「{standard}」',
                    rule_id='custom_glossary',
                ))
        return issues

    def _check_banned_words(self, text: str, banned_words: List[str]) -> List[Issue]:
        """禁用词库检查：用户定义的禁用词，在文本中出现时标记为错误。"""
        issues = []
        for word in banned_words:
            word = word.strip()
            if not word:
                continue
            try:
                pattern = re.compile(re.escape(word))
            except re.error:
                continue
            for match in pattern.finditer(text):
                issues.append(Issue(
                    type='banned_word',
                    severity='error',
                    original=match.group(),
                    suggestion='（请替换或删除该禁用词）',
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'禁用词：「{word}」在禁用词库中，请避免使用',
                    rule_id='banned_word',
                ))
        return issues

    def _check_sensitive(self, text: str, rules: Dict) -> List[Issue]:
        """敏感内容（涉政 / 民族宗教 / 领土规范表述）检查。
        红线词（politics / ethnic_religion）：出现即 error，禁止自动改写，须人工复核。
        领土规范表述（territory_standard）：非标准 -> 标准，warning + 建议替换。
        rules 来自 data/sensitive_rules.json。
        """
        issues = []

        # --- 红线词：涉政 / 民族宗教（出现即 error，不自动改写） ---
        hard_categories = [
            ('sensitive_politics', 'politics'),
            ('sensitive_ethnic_religion', 'ethnic_religion'),
        ]
        for issue_type, key in hard_categories:
            for word in (rules.get(key) or []):
                word = (word or '').strip()
                if not word:
                    continue
                try:
                    pattern = re.compile(re.escape(word))
                except re.error:
                    continue
                for match in pattern.finditer(text):
                    issues.append(Issue(
                        type=issue_type,
                        severity='error',
                        original=match.group(),
                        suggestion=None,  # 红线词不自动改写
                        position=match.start(),
                        end_position=match.end(),
                        context=self._get_context(text, match.start(), match.end()),
                        description=f'敏感内容（红线词）：「{word}」属于合规红线词，出现即违规，须人工复核处理，请勿自动改写',
                        rule_id='sensitive_rules',
                    ))

        # --- 领土 / 称谓规范表述：非标准 -> 标准（warning + 建议替换） ---
        for item in (rules.get('territory_standard') or []):
            if not isinstance(item, dict):
                continue
            bad = (item.get('bad') or '').strip()
            good = (item.get('good') or '').strip()
            if not bad or bad == good:
                continue
            # territory_standard 的 bad 支持正则表达式（如负向后行断言 (?<!中国)），
            # 以便正确形式（如「中国香港」）不被误报为不规范；若正则非法则回退为字面匹配。
            try:
                pattern = re.compile(bad)
            except re.error:
                try:
                    pattern = re.compile(re.escape(bad))
                except re.error:
                    continue
            for match in pattern.finditer(text):
                issues.append(Issue(
                    type='sensitive_territory',
                    severity='warning',
                    original=match.group(),
                    suggestion=good,
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                        description=f'领土/称谓规范表述：根据规范，「{match.group()}」应统一为「{good}」',
                        rule_id='sensitive_rules',
                    ))

        return issues

    def _check_ad_extreme(self, text: str, words: List[str]) -> List[Issue]:
        """广告法极限词（绝对化用语）检查，主要面向营销材料。
        命中即 error（违反《广告法》第九条关于绝对化用语的禁止性规定），不自动改写，
        须人工复核并替换为合规表述。words 来自 data/ad_extreme_words.json。
        """
        issues = []
        for word in (words or []):
            word = (word or '').strip()
            if not word:
                continue
            try:
                pattern = re.compile(re.escape(word))
            except re.error:
                continue
            for match in pattern.finditer(text):
                issues.append(Issue(
                    type='ad_extreme',
                    severity='error',
                    original=match.group(),
                    suggestion=None,  # 绝对化用语须人工替换为合规表述，不自动改写
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description=f'广告法极限词：「{word}」属于绝对化用语，依《广告法》第九条须避免使用，建议删除或替换为合规表述',
                    rule_id='ad_extreme_words',
                ))
        return issues

    def _check_number_format(self, text: str) -> List[Issue]:
        """数字格式检测"""
        issues = []

        # 1. 中文数字与阿拉伯数字"真冗余"检测
        # 设计原则：中文数字与阿拉伯数字混用在大量场景是合法且常见的
        #   （如「10万」「3亿」「2倍」「5百」「3千」「第3章」「2024年」），
        #   不应一律报错。仅在「同一个数量被两种写法紧邻/重复表达」时
        #   （如「5五」「十五15」「二十5」）才提示，避免误报。
        # 计量单位词（十/百/千/万/亿/兆/倍等）紧接阿拉伯数字是标准用法，已通过
        # 将字符类限定为纯数字「零〇一二三四五六七八九」来排除，永不报错。
        cn_digits = '零〇一二三四五六七八九'
        # 阿拉伯数字 紧邻 中文数字（非计量单位词）—— 同一数量重复表达
        mixed_a2c = re.compile(r'(\d+)([' + cn_digits + r'])')
        # 中文数字（非计量单位词，可带十/百/千量级） 紧邻 阿拉伯数字 —— 同一数量重复表达
        # 注意：万/亿不放入量级集合，避免把「一万3千」「100亿3千」这类合法表达误判。
        mixed_c2a = re.compile(r'([' + cn_digits + r'][十百千]*)\d+')
        seen = set()
        for pattern in (mixed_a2c, mixed_c2a):
            for match in pattern.finditer(text):
                seg = match.group()
                if seg in seen:
                    continue
                seen.add(seg)
                issues.append(Issue(
                    type='number_format',
                    severity='info',
                    original=seg,
                    suggestion='（建议统一为单一数字写法，避免同一数量重复表达）',
                    position=match.start(),
                    end_position=match.end(),
                    context=self._get_context(text, match.start(), match.end()),
                    description='同一数量同时用中文数字和阿拉伯数字表达，建议统一',
                    rule_id='mixed_num_format'
                ))

        # 2. 日期格式不一致（如 "2024年" 和 "二〇二四年" 混用）
        # 注意：这是一个「文档级」一致性提醒，不是逐字替换项。
        # 旧实现把全文第一个阿拉伯年份（如 1958年）当作第一个中文年份
        #（如 一九五五年）的 suggestion，会在用户接受修改时把错误年份塞进原文，
        # 产生「一九五五1958年」这类明显错误。因此这里只给出描述性提示。
        arabic_date_pat = re.compile(r'\d{4}年')
        cn_date_pat = re.compile(r'[一二三四五六七八九〇零]{2,4}年')
        arabic_dates = arabic_date_pat.findall(text)
        cn_dates = cn_date_pat.findall(text)
        if arabic_dates and cn_dates:
            # 定位第一个不一致的日期（按出现顺序）
            first_arabic = arabic_date_pat.search(text)
            first_cn = cn_date_pat.search(text)
            if first_arabic and first_cn:
                if first_arabic.start() < first_cn.start():
                    anchor = first_arabic
                    anchor_kind = '阿拉伯数字日期'
                else:
                    anchor = first_cn
                    anchor_kind = '中文数字日期'
                issues.append(Issue(
                    type='number_format',
                    severity='info',
                    original=anchor.group(),
                    suggestion='（建议统一全文日期格式，避免阿拉伯数字与中文数字日期混用）',
                    position=anchor.start(),
                    end_position=anchor.end(),
                    context=self._get_context(text, anchor.start(), anchor.end()),
                    description=f'文档中同时出现阿拉伯数字日期（如「{"、".join(arabic_dates[:3])}」）与中文数字日期（如「{"、".join(cn_dates[:3])}」），建议统一为同一种写法',
                    rule_id='mixed_date_format'
                ))

        # 3. 编号连续性检测（如 1. 2. 4. 缺少 3.）
        # 检测形如 "1." "2." "3." 的编号序列
        numbering_pattern = re.compile(r'^[\s]*(\d+)[\.\、）)]', re.MULTILINE)
        numbers = [int(m.group(1)) for m in numbering_pattern.finditer(text)]
        if len(numbers) >= 3:
            # 检查是否有缺失
            sorted_nums = sorted(set(numbers))
            for i in range(1, len(sorted_nums)):
                if sorted_nums[i] != sorted_nums[i - 1] + 1 and sorted_nums[i] - sorted_nums[i - 1] > 1:
                    missing = sorted_nums[i - 1] + 1
                    # 找到缺失后的第一个编号位置
                    missing_pattern = re.compile(rf'^[\s]*{sorted_nums[i]}[\.\、）)]', re.MULTILINE)
                    m = missing_pattern.search(text)
                    if m:
                        issues.append(Issue(
                            type='number_format',
                            severity='warning',
                            original=f'{sorted_nums[i - 1]}→{sorted_nums[i]}',
                            suggestion=f'编号可能不连续，缺少「{missing}」',
                            position=m.start(),
                            end_position=m.end(),
                            context=self._get_context(text, m.start(), m.end()),
                            description=f'编号从「{sorted_nums[i - 1]}」跳到「{sorted_nums[i]}」，可能缺少「{missing}」，请检查是否遗漏',
                            rule_id='numbering_gap'
                        ))
                    break  # 只报告第一处缺失

        return issues

    def _check_term_consistency(self, text: str) -> List[Issue]:
        """术语一致性检测：同一内容在文档中出现多种写法时提醒统一。

        两种机制：
        (A) 内置等价词表：对常见实体/缩略语（如 苹果公司/Apple公司、人工智能/AI），
            若文档同时出现同一组的≥2种写法，提示统一。
        (B) 同文异写（仅大小写/空格/连字符差异，且为缩写/代号类）：如 iPhone/iphone、
            COVID-19/covid19、V2/v2，归一化后相同但表面写法不一致，提示统一。
        """
        issues = []

        # ---------- (A) 内置等价词表 ----------
        for group in TERM_EQUIVALENCES:
            # 找出文中实际出现的写法及其所有出现区间（最长优先匹配，避免「Apple」误命中「Apple公司」）
            forms_sorted = sorted(set(group), key=len, reverse=True)
            prefix_forms = set()
            for f in group:
                for g in group:
                    if len(g) > len(f) and g.startswith(f):
                        prefix_forms.add(f)
            present = {}  # form -> [(start, end), ...]
            i, n = 0, len(text)
            while i < n:
                matched = None
                for f in forms_sorted:
                    flen = len(f)
                    if i + flen > n:
                        continue
                    seg = text[i:i + flen]
                    if re.search(r'[A-Za-z]', f):
                        if seg.lower() != f.lower():
                            continue
                        before = text[i - 1] if i > 0 else ''
                        after = text[i + flen] if i + flen < n else ''
                        # 必须是完整词块：前后不能是 ASCII 字母或数字
                        # （避免 AI 误入 MAIL、COVID 误入 covid19；中文前后不算字母）
                        if ('a' <= before.lower() <= 'z') or before.isdigit():
                            continue
                        if ('a' <= after.lower() <= 'z') or after.isdigit():
                            continue
                        # 若该写法是其它更长写法的词干前缀（如 Apple 是 Apple公司 的前缀），
                        # 其后紧接中文时视为更长写法的一部分，不单独计
                        if f in prefix_forms and ('\u4e00' <= after <= '\u9fa5'):
                            continue
                    else:
                        if seg != f:
                            continue
                    matched = f
                    break
                if matched:
                    present.setdefault(matched, []).append((i, i + len(matched)))
                    i += len(matched)
                else:
                    i += 1
            forms_present = set(present.keys())
            if len(forms_present) < 2:
                continue
            # 仅当两种写法紧邻且中间仅用括号/引号/标点分隔（如「苹果公司（Apple公司）」）
            # 才视为释义/定义，不报；普通相邻（如「人工智能是AI…」）仍报。
            sep_chars = set('（）()[]{}""\'\'、·—～,，。；:：')
            is_definition = False
            flist = list(present.items())
            for a in range(len(flist)):
                for b in range(a + 1, len(flist)):
                    for s1 in flist[a][1]:
                        for s2 in flist[b][1]:
                            lo, hi = (s1, s2) if s1[0] <= s2[0] else (s2, s1)
                            gap = text[lo[1]:hi[0]]
                            if 0 <= len(gap) <= 2 and (gap == '' or all(c in sep_chars for c in gap)):
                                is_definition = True
                                break
                        if is_definition:
                            break
                    if is_definition:
                        break
                if is_definition:
                    break
            if is_definition:
                continue
            canonical = group[0]
            anchor_form = next((f for f in forms_present if f != canonical), list(forms_present)[0])
            anchor_pos = min(s[0] for s in present[anchor_form])
            variants = ' / '.join(sorted(forms_present))
            issues.append(Issue(
                type='term_consistency',
                severity='warning',
                original=anchor_form,
                suggestion=canonical,
                position=anchor_pos,
                end_position=anchor_pos + len(anchor_form),
                context=self._get_context(text, anchor_pos, anchor_pos + len(anchor_form)),
                description=f'文档中「{variants}」指代同一内容但写法不统一，建议统一为「{canonical}」',
                rule_id='term_equivalence'
            ))

        # ---------- (B) 同文异写（仅大小写/空格/连字符差异，且为缩写/代号类） ----------
        TERM_STOPWORDS = {'a', 'an', 'the', 'us', 'is', 'in', 'on', 'at', 'of', 'to', 'be', 'by', 'for',
                          'or', 'and', 'it', 'as', 'so', 'no', 'ok', 'id', 'ip', 'vs', 'me', 'he', 'she',
                          'we', 'do', 'go', 'hi', 'oh', 'pm', 'am', 'up', 'off', 'out', 'my'}

        def _is_term_like(s: str) -> bool:
            """判断是否为缩写/代号类术语（而非普通英文单词），用于降噪。"""
            if any(c.isdigit() for c in s):
                return True
            if '-' in s or '.' in s:
                return True
            if s.isupper() and 2 <= len(s) <= 5:
                return True
            # 内部大写（CamelCase，如 iPhone、iOS、macOS）
            if any(c.isupper() for c in s[1:]):
                return True
            return False

        token_pat = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*')
        norm_map = {}  # norm -> {surface: count}
        for tok in token_pat.findall(text):
            norm = re.sub(r'[\s\-]', '', tok).lower()
            if len(norm) < 2 or norm in TERM_STOPWORDS:
                continue
            norm_map.setdefault(norm, {})
            norm_map[norm][tok] = norm_map[norm].get(tok, 0) + 1
        for norm, surfaces in norm_map.items():
            distinct = list(surfaces.keys())
            if len(distinct) < 2:
                continue
            # 仅当至少一种写法像术语（含数字/连字符/内部大写/全大写缩写）才报，避免普通单词大小写差异
            if not any(_is_term_like(s) for s in distinct):
                continue
            canonical = max(distinct, key=lambda s: surfaces[s])  # 出现次数最多者为规范
            anchor_form = next((s for s in distinct if s != canonical), distinct[0])
            m = re.search(r'(?<![A-Za-z])' + re.escape(anchor_form) + r'(?![A-Za-z])', text) \
                or re.search(re.escape(anchor_form), text)
            pos = m.start() if m else 0
            variants = ' / '.join(sorted(distinct))
            issues.append(Issue(
                type='term_consistency',
                severity='warning',
                original=anchor_form,
                suggestion=canonical,
                position=pos,
                end_position=pos + len(anchor_form),
                context=self._get_context(text, pos, pos + len(anchor_form)),
                description=f'文档中「{variants}」为同一术语的异写（仅大小写/空格/连字符不同），建议统一为「{canonical}」',
                rule_id='term_variant'
            ))

        return issues

    # ============================================================
    # 敏感信息（PII）合规扫描
    # ============================================================
    def _check_pii(self, text: str) -> List[Issue]:
        """合规/安全层：识别身份证、手机号、邮箱、银行卡、密钥/凭证等个人敏感信息
        或凭据泄露风险，便于用户在外发文档前进行脱敏。

        设计原则：
        - 身份证、银行卡均带校验位（GB11643 / Luhn），显著降低误报；
        - 手机号限定 1[3-9] 开头 11 位；
        - 密钥/凭证采用高精确度签名，避免普通文本误报；
        - 纯数字串按「身份证 > 银行卡 > 手机号」优先级分类，避免同一串重复标记；
        - severity 统一为 error，天然不进入 LLM 语义复核（仅 warning/info 参与），
          保证合规问题不被误判为「误报」而剔除。
        """
        issues: List[Issue] = []
        used: List[Tuple[int, int]] = []  # 已被占用的区间，避免重复标

        def _overlap(s: int, e: int) -> bool:
            return any(s < ue and e > us for (us, ue) in used)

        def _add(s: int, e: int, type_: str, desc: str) -> None:
            issues.append(Issue(
                type=type_,
                severity='error',
                original=text[s:e],
                suggestion='***',
                position=s,
                end_position=e,
                context=self._get_context(text, s, e),
                description=desc,
                rule_id=type_,
            ))

        # 1) 纯数字串分类：身份证(18,校验) > 银行卡(15-19,Luhn) > 手机号(11,1[3-9])
        for m in _PI_DIGIT_RUN.finditer(text):
            val = m.group(1)
            s, e = m.start(1), m.end(1)
            if _overlap(s, e):
                continue
            if len(val) == 18 and _valid_id_card(val):
                used.append((s, e))
                _add(s, e, 'pii_id', '身份证号属于个人敏感信息，建议脱敏或删除后再外发')
            elif val.isdigit() and 15 <= len(val) <= 19 and _luhn_valid(val):
                used.append((s, e))
                _add(s, e, 'pii_bank', '银行卡号属于个人金融敏感信息，建议脱敏或删除后再外发')
            elif len(val) == 11 and re.fullmatch(r'1[3-9]\d{9}', val):
                used.append((s, e))
                _add(s, e, 'pii_phone', '手机号属于个人敏感信息，建议脱敏或删除后再外发')
            # 其余数字串（如订单号、随机长数字）不报，避免误报

        # 2) 邮箱地址
        for m in _PI_EMAIL_PAT.finditer(text):
            s, e = m.start(), m.end()
            if _overlap(s, e):
                continue
            used.append((s, e))
            _add(s, e, 'pii_email', '邮箱地址属于个人敏感信息，建议脱敏或删除后再外发')

        # 3) 密钥 / 凭证
        for pat in _PI_KEY_PATS:
            for m in pat.finditer(text):
                s, e = m.start(), m.end()
                if _overlap(s, e):
                    continue
                used.append((s, e))
                _add(s, e, 'pii_key', '疑似密钥或凭证泄露，建议移除或替换为占位符后再外发')

        return issues

    def get_summary(self, issues: List[Issue]) -> dict:
        """生成问题摘要统计"""
        summary = {
            'total': len(issues),
            'by_type': {},
            'by_severity': {},
            'by_rule': {},
            'by_layer': {},
        }
        type_names = {
            'typo': '错别字',
            'variant_char': '异形词',
            'width_mixed': '全半角混用',
            'missing_char': '漏字/缺字',
            'idiom_misuse': '成语误用',
            'expression': '语病/表达',
            'grammar': '语法',
            'logic': '逻辑',
            'punctuation': '标点符号',
            'spacing': '多余空格',
            'number_format': '数字/格式',
            'repetition': '重复词语',
            'style': '文风/格式',
            'colloquial': '口语化',
            'term_consistency': '术语不一致',
            'pii_id': '身份证号',
            'pii_phone': '手机号',
            'pii_email': '邮箱地址',
            'pii_bank': '银行卡号',
            'pii_key': '密钥/凭证',
        }
        severity_names = {
            'error': '错误',
            'warning': '警告',
            'info': '建议',
        }
        for issue in issues:
            type_cn = type_names.get(issue.type, issue.type)
            sev_cn = severity_names.get(issue.severity, issue.severity)
            layer_cn = LAYER_NAMES.get(issue.layer, issue.layer)
            summary['by_type'][type_cn] = summary['by_type'].get(type_cn, 0) + 1
            summary['by_severity'][sev_cn] = summary['by_severity'].get(sev_cn, 0) + 1
            summary['by_rule'][issue.rule_id] = summary['by_rule'].get(issue.rule_id, 0) + 1
            summary['by_layer'][layer_cn] = summary['by_layer'].get(layer_cn, 0) + 1
        return summary

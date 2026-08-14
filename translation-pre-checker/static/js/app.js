/**
 * 啄木鸟·中英文字智能检查 - 前端逻辑
 */

// 六层检查体系定义
const LAYERS = [
    { id: 'character',  name: '字符层',       icon: 'A文', focus: ['错别字', '异形词', '全半角混用', '漏字/缺字'] },
    { id: 'vocabulary', name: '词汇层',       icon: '词', focus: ['成语误用', '术语一致性', '自定义术语'] },
    { id: 'sentence',   name: '句子层',       icon: '句', focus: ['语法结构', '表达歧义', '逻辑连贯'] },
    { id: 'format',     name: '标点/格式层',   icon: '符', focus: ['标点符号', '多余空格', '数字/格式'] },
    { id: 'discourse',  name: '语篇/语体层',   icon: '篇', focus: ['重复词语', '文风统一', '口语化', '禁用词'] },
    { id: 'security',   name: '合规/安全层',   icon: '盾', focus: ['身份证号', '手机号', '邮箱地址', '银行卡号', '密钥/凭证', '敏感词/红线', '领土规范表述', '广告法极限词'] },
];

// 各层面主题色（与 .issue-card.layer-* 的 --layer-color 保持一致），用于上传区模块展示
const LAYER_COLORS = {
    character:  '#f87171',
    vocabulary: '#fb923c',
    sentence:   '#a78bfa',
    format:     '#38bdf8',
    discourse:  '#34d399',
    security:   '#f59e0b',
};

// 在上传区底部渲染六层检查模块（图标 + 名称 + 检查重点 + 主题色）
function renderLayerModules() {
    const container = document.getElementById('layerModules');
    if (!container) return;
    container.innerHTML = LAYERS.map(layer => {
        const color = LAYER_COLORS[layer.id] || '#64748b';
        const isSecurity = layer.id === 'security';
        const focusItems = layer.focus.map(f => `<li>${f}</li>`).join('');
        return `
            <div class="layer-module${isSecurity ? ' layer-module-security' : ''}" style="--lm-color: ${color}">
                <div class="layer-module-head">
                    <span class="layer-module-icon">${layer.icon}</span>
                    <span class="layer-module-name">${layer.name}</span>
                </div>
                <ul class="layer-module-focus">${focusItems}</ul>
            </div>`;
    }).join('');
}

// 问题类型标签映射（英文 -> 中文显示）
const TYPE_LABELS = {
    'typo': '错别字',
    'variant_char': '异形词',
    'width_mixed': '全半角混用',
    'missing_char': '漏字/缺字',
    'idiom_misuse': '成语误用',
    'custom_term': '自定义术语',
    'expression': '语病/表达',
    'grammar': '语法',
    'logic': '逻辑',
    'punctuation': '标点符号',
    'spacing': '多余空格',
    'number_format': '数字/格式',
    'repetition': '重复词语',
    'style': '文风/格式',
    'colloquial': '口语化',
    'banned_word': '禁用词',
    'term_consistency': '术语不一致',
    'pii_id': '身份证号',
    'pii_phone': '手机号',
    'pii_email': '邮箱地址',
    'pii_bank': '银行卡号',
    'pii_key': '密钥/凭证',
    'sensitive_politics': '涉政敏感词',
    'sensitive_ethnic_religion': '民族宗教敏感词',
    'sensitive_territory': '领土规范表述',
    'ad_extreme': '广告法极限词',
};

// type -> layer 映射（与后端一致）
const TYPE_TO_LAYER = {
    'typo': 'character', 'variant_char': 'character', 'width_mixed': 'character',
    'missing_char': 'vocabulary', 'idiom_misuse': 'vocabulary', 'custom_term': 'vocabulary',
    'expression': 'sentence', 'grammar': 'sentence', 'logic': 'sentence',
    'punctuation': 'format', 'spacing': 'format', 'number_format': 'format',
    'repetition': 'discourse', 'style': 'discourse', 'colloquial': 'discourse', 'banned_word': 'discourse',
    'term_consistency': 'vocabulary',
    'pii_id': 'security', 'pii_phone': 'security', 'pii_email': 'security',
    'pii_bank': 'security', 'pii_key': 'security',
    'sensitive_politics': 'security', 'sensitive_ethnic_religion': 'security',
    'sensitive_territory': 'security',
    'ad_extreme': 'security',
};

// 层级中文名
const LAYER_NAMES = {
    'character': '字符层',
    'vocabulary': '词汇层',
    'sentence': '句子层',
    'format': '标点/格式层',
    'discourse': '语篇/语体层',
    'security': '合规/安全层',
};

// 全局状态
let currentResult = null;
let issueStates = {}; // { index: 'accepted' | 'rejected' | 'pending' }
let previewMode = false;
let editMode = false;
let segView = true; // 句段视图（一句一行 + 行号），类似 TRADOS/MEMOQ 编辑器
let selectedScenario = 'general'; // 检查场景
let securityEnabled = true;      // 合规/安全层（PII）扫描开关，默认开启
let sensitiveEnabled = true;     // 政治性/敏感词（涉政·民族宗教·领土规范表述）检查开关，默认开启
let adExtremeEnabled = false;    // 广告法极限词（营销材料）检查开关，默认关闭，需用户显式开启

// 查找替换状态
// findState.matches: [{s, e}] 绝对位置（相对 currentResult.text）
let findState = { query: '', caseSensitive: false, activeIndex: -1, matches: [], scrollAfterRender: false };
// 用户查找替换产生的替换对（键=被替换串），用于文件模式导出时合并到后端替换列表
let userReplacements = {};

// 批量操作撤销快照
let lastBatchSnapshot = null;
let batchUndoTimer = null;

// ============================================================
// 检查场景选择
// ============================================================
// 合规/安全层（PII）扫描开关：默认开启；点击切换后同步摘要条与提交参数
function toggleSecurity(event) {
    // 阻止 label 默认行为导致 checkbox 被点两次（一次 label 一次 input）
    event.preventDefault();
    securityEnabled = !securityEnabled;
    const cb = document.getElementById('securityToggle');
    if (cb) cb.checked = securityEnabled;
    renderSettingsSummary();
    saveSessionState();
}

// 政治性/敏感词检查开关：默认开启；点击切换后同步摘要条与提交参数
function toggleSensitive(event) {
    event.preventDefault();
    sensitiveEnabled = !sensitiveEnabled;
    const cb = document.getElementById('sensitiveToggle');
    if (cb) cb.checked = sensitiveEnabled;
    renderSettingsSummary();
    saveSessionState();
}

// 广告法极限词（营销材料）检查开关：默认关闭；点击切换后同步摘要条与提交参数
function toggleAdExtreme(event) {
    event.preventDefault();
    adExtremeEnabled = !adExtremeEnabled;
    const cb = document.getElementById('adExtremeToggle');
    if (cb) cb.checked = adExtremeEnabled;
    renderSettingsSummary();
    saveSessionState();
}

function selectScenario(scenario) {
    selectedScenario = scenario;
    document.querySelectorAll('.scenario-card').forEach(card => {
        card.classList.toggle('active', card.dataset.scenario === scenario);
    });
    renderSettingsSummary();
}

const SCENARIO_NAMES = {
    general: '通用文档', academic: '学术论文', business: '商务文档',
    legal: '法律文书', news: '新闻稿', technical: '技术文档'
};

// 常驻「检查设置」摘要条：让用户随时看到当前场景/术语/禁用词状态
function renderSettingsSummary() {
    const ssScenario = document.getElementById('ssScenario');
    const ssTerms = document.getElementById('ssTerms');
    const ssBanned = document.getElementById('ssBanned');
    const ssSecurity = document.getElementById('ssSecurity');
    const ssSensitive = document.getElementById('ssSensitive');
    const ssAdExtreme = document.getElementById('ssAdExtreme');
    if (!ssScenario) return;
    ssScenario.textContent = SCENARIO_NAMES[selectedScenario] || '通用文档';
    ssTerms.textContent = glossaryTerms.length + ' 条';
    ssBanned.textContent = bannedWords.length + ' 个';
    if (ssSecurity) ssSecurity.textContent = securityEnabled ? '开启' : '关闭';
    if (ssSensitive) ssSensitive.textContent = sensitiveEnabled ? '开启' : '关闭';
    if (ssAdExtreme) ssAdExtreme.textContent = adExtremeEnabled ? '开启' : '关闭';
}

// 展开「检查设置」侧栏标签（供「去设置」调用）；新布局中设置统一收拢到右侧资源栏
function openGlossaryPanel() {
    switchSidebarTab('settings');
}

// 检查前友好确认：术语表/禁用词为空时温和提醒，避免用户漏设配置
let _pendingProceed = null;
// 暂存"待上传"的源（文件或文本），仅在「确认弹窗」展示期间短暂存在；
// 确认关闭（仍要检查/取消）或「去设置」后都会被消费或清空，不会残留旧文件。
let _deferredUpload = null; // { kind: 'file', file } | { kind: 'text', text }
// 标记：确认弹窗本会话已确认过一次（避免对可选设置反复打扰、陷入"去设置"死循环）
let _settingsAcknowledged = false;

function maybeConfirmSettings(proceedFn) {
    const termsEmpty = glossaryTerms.length === 0;
    const bannedEmpty = bannedWords.length === 0;
    // 术语表与禁用词均为可选：要么已设置，要么本会话已确认过弹窗，则直接检查
    if (_settingsAcknowledged || (!termsEmpty && !bannedEmpty)) {
        proceedFn();
        return;
    }
    document.getElementById('csScenario').textContent = SCENARIO_NAMES[selectedScenario] || '通用文档';
    document.getElementById('csTerms').textContent = termsEmpty ? '未设置' : (glossaryTerms.length + ' 条');
    document.getElementById('csBanned').textContent = bannedEmpty ? '未设置' : (bannedWords.length + ' 个');
    const tip = document.getElementById('csTip');
    if (termsEmpty && bannedEmpty) {
        tip.textContent = '你还没有设置「自定义术语表」和「禁用词库」，系统将仅做通用检查。补充后术语一致性和禁用词检查会更准确。';
    } else if (termsEmpty) {
        tip.textContent = '你还没有设置「自定义术语表」，可能影响术语一致性检查效果。';
    } else {
        tip.textContent = '你还没有设置「禁用词库」，相关词汇将不会被标记。';
    }
    tip.classList.toggle('confirm-tip-warn', termsEmpty || bannedEmpty);
    _pendingProceed = proceedFn;
    document.getElementById('settingsConfirmOverlay').style.display = 'flex';
}

function closeSettingsConfirm(goSet) {
    document.getElementById('settingsConfirmOverlay').style.display = 'none';
    // 无论选「去设置」还是「仍要检查」，本会话都视为已确认过，后续上传不再反复弹窗
    _settingsAcknowledged = true;
    if (goSet) {
        // 「去设置」：丢弃本次挂起的上传，避免残留旧文件。
        // 新布局下设置常驻右侧栏，没有「关闭面板」事件来触发自动恢复上传；
        // 若保留 _deferredUpload，之后点「开始检查」会误上传旧文件（同名文件 change 不触发，
        // 看起来像"传不上去"）。用户稍后从上传区重新选择或点「开始检查」即可，
        // 输入框里的文件选择本身并未丢失，triggerStart 会重新读取。
        _pendingProceed = null;
        _deferredUpload = null;
        openGlossaryPanel();
    } else if (_pendingProceed) {
        const fn = _pendingProceed;
        _pendingProceed = null;
        fn();
    }
}

// ============================================================
// 自定义术语表 / 禁用词库（localStorage 持久化）
// ============================================================
// 术语表和禁用词库仅存内存，检查完成后自动清除
let glossaryTerms = []; // [{original, standard}]
let bannedWords = [];   // ["word1", "word2"]

function loadGlossary() {
    // 不从 localStorage 恢复，每次页面加载为空
    glossaryTerms = [];
    bannedWords = [];
    // 清除旧版本遗留的 localStorage 数据
    localStorage.removeItem('woodpecker_glossary');
    localStorage.removeItem('woodpecker_banned');
}

function saveGlossary() {
    // 不持久化到 localStorage
}

// 保存本次检查使用的术语数据，供"重新检查"复用
let _lastCheckGlossary = '';
let _lastCheckBanned = '';

// 旧版 glossaryPanel 折叠逻辑已废弃（面板改为右侧资源栏标签），相关引用见 switchSidebarTab

function switchGlossaryTab(tab) {
    document.querySelectorAll('.glossary-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tab);
    });
    document.getElementById('termsTab').classList.toggle('active', tab === 'terms');
    document.getElementById('bannedTab').classList.toggle('active', tab === 'banned');
}

function addGlossaryTerm() {
    const origInput = document.getElementById('termOriginal');
    const stdInput = document.getElementById('termStandard');
    const orig = origInput.value.trim();
    const std = stdInput.value.trim();
    if (!orig || !std) {
        showToast('请填写原文写法和规范写法', 'warning');
        return;
    }
    if (orig === std) {
        showToast('原文写法与规范写法不能相同', 'warning');
        return;
    }
    // 去重
    if (glossaryTerms.some(t => t.original === orig && t.standard === std)) {
        showToast('该术语对已存在', 'warning');
        return;
    }
    glossaryTerms.push({ original: orig, standard: std });
    saveGlossary();
    renderGlossaryTerms();
    origInput.value = '';
    stdInput.value = '';
    origInput.focus();
}

function removeGlossaryTerm(idx) {
    glossaryTerms.splice(idx, 1);
    saveGlossary();
    renderGlossaryTerms();
}

function addBannedWord() {
    const input = document.getElementById('bannedInput');
    const word = input.value.trim();
    if (!word) return;
    if (bannedWords.includes(word)) {
        showToast('该禁用词已存在', 'warning');
        return;
    }
    bannedWords.push(word);
    saveGlossary();
    renderBannedWords();
    input.value = '';
    input.focus();
}

function removeBannedWord(idx) {
    bannedWords.splice(idx, 1);
    saveGlossary();
    renderBannedWords();
}

function renderGlossaryTerms() {
    const list = document.getElementById('glossaryTermList');
    document.getElementById('termsCount').textContent = glossaryTerms.length;
    updateGlossaryToggleCount();
    if (glossaryTerms.length === 0) {
        list.innerHTML = '<div class="glossary-empty">暂无自定义术语，添加后将自动检查术语一致性</div>';
        return;
    }
    list.innerHTML = glossaryTerms.map((t, i) => `
        <div class="glossary-item">
            <span class="glossary-item-orig">${escapeHtml(t.original)}</span>
            <span class="glossary-item-arrow">→</span>
            <span class="glossary-item-std">${escapeHtml(t.standard)}</span>
            <button class="glossary-item-del" onclick="removeGlossaryTerm(${i})" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </div>
    `).join('');
}

function renderBannedWords() {
    const list = document.getElementById('bannedWordList');
    document.getElementById('bannedCount').textContent = bannedWords.length;
    updateGlossaryToggleCount();
    if (bannedWords.length === 0) {
        list.innerHTML = '<div class="glossary-empty">暂无禁用词，添加后将自动检测文本中的禁用词</div>';
        return;
    }
    list.innerHTML = bannedWords.map((w, i) => `
        <span class="banned-chip">
            <span>${escapeHtml(w)}</span>
            <button class="banned-chip-del" onclick="removeBannedWord(${i})" title="删除">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </span>
    `).join('');
}

function updateGlossaryToggleCount() {
    const total = glossaryTerms.length + bannedWords.length;
    // glossaryToggleCount 聚合徽标在 YiCAT 布局重排后已不再使用（计数改由
    // 术语库/禁用词侧栏标签上的 termsCount/bannedCount 承载）。元素可能不存在，
    // 必须安全降级，否则会在加载期抛错并中断其后所有初始化。
    const el = document.getElementById('glossaryToggleCount');
    if (el) {
        if (total > 0) {
            el.textContent = total + ' 项';
            el.style.display = '';
        } else {
            el.style.display = 'none';
        }
    }
    renderSettingsSummary();
}

function getGlossaryJSON() {
    return glossaryTerms.length > 0 ? JSON.stringify(glossaryTerms) : '';
}

function getBannedWordsJSON() {
    return bannedWords.length > 0 ? JSON.stringify(bannedWords) : '';
}

// ============================================================
// 术语表 / 禁用词库：文件上传导入
// ============================================================

/**
 * 解析术语表文件（CSV/TXT/TSV）
 * 支持格式：每行 "原文,规范" 或 "原文\t规范" 或 "原文→规范"
 * 忽略空行和以 # 开头的注释行
 */
function handleGlossaryFileUpload(input) {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
        const text = e.target.result;
        const lines = text.split(/\r?\n/);
        let added = 0, skipped = 0;
        lines.forEach(line => {
            line = line.trim();
            if (!line || line.startsWith('#')) return;
            // 尝试用逗号、制表符或 → 分割
            let parts;
            if (line.includes('\t')) {
                parts = line.split('\t');
            } else if (line.includes('→')) {
                parts = line.split('→');
            } else {
                parts = line.split(',');
            }
            if (parts.length >= 2) {
                const orig = parts[0].trim().replace(/^["']|["']$/g, '');
                const std = parts[1].trim().replace(/^["']|["']$/g, '');
                if (orig && std && orig !== std) {
                    if (!glossaryTerms.some(t => t.original === orig && t.standard === std)) {
                        glossaryTerms.push({ original: orig, standard: std });
                        added++;
                    } else {
                        skipped++;
                    }
                } else {
                    skipped++;
                }
            } else {
                skipped++;
            }
        });
        renderGlossaryTerms();
        input.value = ''; // 重置以便可重复上传同一文件
        if (added > 0) {
            const msg = `成功导入 ${added} 条术语` + (skipped > 0 ? `（跳过 ${skipped} 行无效或重复）` : '');
            showToast(msg, 'success');
        } else {
            showToast('未导入任何术语，请检查文件格式（每行：原文,规范）', 'warning');
        }
    };
    reader.readAsText(file, 'UTF-8');
}

/**
 * 解析禁用词文件（CSV/TXT/TSV）
 * 每行一个禁用词，忽略空行和注释行
 */
function handleBannedFileUpload(input) {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
        const text = e.target.result;
        const lines = text.split(/\r?\n/);
        let added = 0, skipped = 0;
        lines.forEach(line => {
            line = line.trim().replace(/^["']|["']$/g, '');
            if (!line || line.startsWith('#')) return;
            // 如果一行有多个词用逗号分隔，全部导入
            const words = line.split(/[,\t]/).map(w => w.trim()).filter(w => w);
            words.forEach(word => {
                if (!bannedWords.includes(word)) {
                    bannedWords.push(word);
                    added++;
                } else {
                    skipped++;
                }
            });
        });
        renderBannedWords();
        input.value = '';
        if (added > 0) {
            const msg = `成功导入 ${added} 个禁用词` + (skipped > 0 ? `（跳过 ${skipped} 个重复）` : '');
            showToast(msg, 'success');
        } else {
            showToast('未导入任何禁用词，请检查文件格式（每行一个词）', 'warning');
        }
    };
    reader.readAsText(file, 'UTF-8');
}

/**
 * 下载术语表示例文件
 */
function downloadSampleGlossary() {
    const content = '# 术语表示例文件\n# 每行格式：原文,规范（支持逗号、制表符或 → 分隔）\n# 以 # 开头的行为注释，将被忽略\nAI,人工智能\nVR,虚拟现实\nAR,增强现实\nAPP,应用程序\nOS,操作系统\n';
    const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '术语表示例.csv';
    a.click();
    URL.revokeObjectURL(a.href);
    showToast('示例文件已下载', 'success');
}

/**
 * 下载禁用词示例文件
 */
function downloadSampleBanned() {
    const content = '# 禁用词示例文件\n# 每行一个禁用词（也可用逗号分隔多个）\n# 以 # 开头的行为注释，将被忽略\n垃圾\n废话\n胡说\n随便\n差不多\n';
    const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '禁用词示例.csv';
    a.click();
    URL.revokeObjectURL(a.href);
    showToast('示例文件已下载', 'success');
}

/**
 * 检查完成后清除术语表和禁用词库
 */
function clearGlossaryAfterCheck() {
    glossaryTerms = [];
    bannedWords = [];
    renderGlossaryTerms();
    renderBannedWords();
}

/**
 * 轻量 Toast 提示（替代 alert）
 */
function showToast(message, type) {
    type = type || 'info';
    let toast = document.getElementById('glossaryToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'glossaryToast';
        toast.className = 'glossary-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = 'glossary-toast glossary-toast-' + type;
    toast.style.display = 'block';
    // 触发重排后添加 show 类以触发动画
    void toast.offsetWidth;
    toast.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => { toast.style.display = 'none'; }, 300);
    }, 3000);
}

/**
 * 通用确认弹窗（替代原生 confirm，返回 Promise<boolean>）
 */
let _confirmResolve = null;
function confirmDialog(message) {
    return new Promise(resolve => {
        _confirmResolve = resolve;
        const overlay = document.getElementById('confirmDialog');
        document.getElementById('confirmDialogMessage').textContent = message;
        overlay.style.display = 'flex';
    });
}
function _closeConfirm(result) {
    document.getElementById('confirmDialog').style.display = 'none';
    if (_confirmResolve) {
        _confirmResolve(result);
        _confirmResolve = null;
    }
}
document.getElementById('confirmDialogOk').addEventListener('click', () => _closeConfirm(true));
document.getElementById('confirmDialogCancel').addEventListener('click', () => _closeConfirm(false));
document.getElementById('confirmDialog').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) _closeConfirm(false);
});

// ============================================================
// 会话持久化：防止刷新/关闭页面导致审阅进度丢失
// ============================================================
const SESSION_KEY = 'woodpecker_session';

function saveSessionState() {
    if (!currentResult) {
        clearSessionState();
        return;
    }
    try {
        const state = {
            currentResult: currentResult,
            issueStates: issueStates,
            scenario: selectedScenario,
            securityEnabled: securityEnabled,
            sensitiveEnabled: sensitiveEnabled,
            adExtremeEnabled: adExtremeEnabled,
        };
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(state));
    } catch (e) {
        // sessionStorage 可能超限（大文件），静默忽略
        console.warn('会话状态保存失败（可能超出存储限制）:', e);
    }
}

function clearSessionState() {
    sessionStorage.removeItem(SESSION_KEY);
}

function tryRestoreSession() {
    try {
        const raw = sessionStorage.getItem(SESSION_KEY);
        if (!raw) return false;
        const state = JSON.parse(raw);
        if (!state.currentResult || !state.currentResult.issues) return false;

        currentResult = state.currentResult;
        issueStates = state.issueStates || {};
        if (state.scenario) {
            selectedScenario = state.scenario;
            selectScenario(selectedScenario);
        }
        if (typeof state.securityEnabled === 'boolean') {
            securityEnabled = state.securityEnabled;
            const cb = document.getElementById('securityToggle');
            if (cb) cb.checked = securityEnabled;
        }
        if (typeof state.sensitiveEnabled === 'boolean') {
            sensitiveEnabled = state.sensitiveEnabled;
            const cb = document.getElementById('sensitiveToggle');
            if (cb) cb.checked = sensitiveEnabled;
        }
        if (typeof state.adExtremeEnabled === 'boolean') {
            adExtremeEnabled = state.adExtremeEnabled;
            const cb = document.getElementById('adExtremeToggle');
            if (cb) cb.checked = adExtremeEnabled;
        }
        previewMode = false;
        editMode = false;

        // 确保 UI 元素状态正确
        document.getElementById('editArea').classList.remove('is-visible');
        document.getElementById('annotatedText').style.display = 'block';
        const editBtn = document.getElementById('editToggle');
        if (editBtn) {
            editBtn.classList.remove('active');
            editBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> 编辑原文`;
        }

        enterResultView();

        renderStats(currentResult);
        renderAnnotatedText(currentResult);
        renderIssueList(currentResult);
        updateActionToolbar();

        // 显示恢复提示
        showSessionRestoredHint();

        return true;
    } catch (e) {
        clearSessionState();
        return false;
    }
}

function showSessionRestoredHint() {
    const hint = document.createElement('div');
    hint.className = 'session-restored-hint';
    hint.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
        <span>已恢复上次审阅进度</span>
    `;
    document.body.appendChild(hint);
    requestAnimationFrame(() => hint.classList.add('show'));
    setTimeout(() => {
        hint.classList.remove('show');
        setTimeout(() => hint.remove(), 400);
    }, 3500);
}

// ============================================================
// 主题切换（夜间模式 / 护眼模式）
// ============================================================
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    if (next === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('theme', next);
}

// 检查阶段步骤（带图标）
const STEP_ICONS = {
    upload: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
    text: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg>',
    read: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
    stats: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    typo: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    punctuation: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    spacing: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>',
    missing: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>',
    repetition: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    expression: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="13" x2="13" y2="13"/></svg>',
    generate: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4-6.2-4.5-6.2 4.5 2.4-7.4L2 9.4h7.6z"/></svg>',
};

const LOADING_STEPS_FILE = [
    { icon: STEP_ICONS.upload, text: '文件上传成功' },
    { icon: STEP_ICONS.read,   text: '正在阅读文件内容' },
    { icon: STEP_ICONS.stats,  text: '正在统计字数与段落' },
    { icon: STEP_ICONS.typo,   text: '正在检查字符层（错别字、异形词、全半角）' },
    { icon: STEP_ICONS.missing, text: '正在检查词汇层（漏字、成语误用）' },
    { icon: STEP_ICONS.expression, text: '正在检查句子层（语病、语法、逻辑）' },
    { icon: STEP_ICONS.punctuation, text: '正在检查标点/格式层（标点、空格、数字）' },
    { icon: STEP_ICONS.repetition, text: '正在检查语篇/语体层（重复、口语化）' },
    { icon: STEP_ICONS.generate, text: '正在生成修改建议' },
];

const LOADING_STEPS_TEXT = [
    { icon: STEP_ICONS.text,   text: '文本已接收' },
    { icon: STEP_ICONS.read,   text: '正在解析文本内容' },
    { icon: STEP_ICONS.stats,  text: '正在统计字数与段落' },
    { icon: STEP_ICONS.typo,   text: '正在检查字符层（错别字、异形词、全半角）' },
    { icon: STEP_ICONS.missing, text: '正在检查词汇层（漏字、成语误用）' },
    { icon: STEP_ICONS.expression, text: '正在检查句子层（语病、语法、逻辑）' },
    { icon: STEP_ICONS.punctuation, text: '正在检查标点/格式层（标点、空格、数字）' },
    { icon: STEP_ICONS.repetition, text: '正在检查语篇/语体层（重复、口语化）' },
    { icon: STEP_ICONS.generate, text: '正在生成修改建议' },
];

let loadingStepIdx = 0;
let loadingTimer = null;
let loadingResult = null;
let loadingResultIsError = false;
let loadingStepsArr = [];

// ============================================================
// 模式切换
// ============================================================
// 当前输入方式（file / text），供工具栏「开始检查」判断走哪条上传路径
let currentInputMode = 'file';

// 切换「上传文件 / 粘贴文本」输入方式（仅作用于上传区内的标签与内容，不影响顶部工作区标签）
function switchInputMode(mode) {
    currentInputMode = mode;
    const container = document.getElementById('uploadSection');
    if (!container) return;
    container.querySelectorAll('.mode-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.mode === mode);
    });
    const fileMode = document.getElementById('fileMode');
    const textMode = document.getElementById('textMode');
    if (fileMode) fileMode.classList.toggle('active', mode === 'file');
    if (textMode) textMode.classList.toggle('active', mode === 'text');
}

// ============================================================
// 文件上传
// ============================================================
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');

dropzone.addEventListener('click', () => fileInput.click());

dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
});

dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dragover');
});

dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
    }
});

function handleFile(file) {
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
        showToast('文件大小不能超过 10MB', 'warning');
        return;
    }

    const allowedExts = ['txt', 'docx', 'doc', 'pdf', 'rtf', 'md', 'csv'];
    const ext = file.name.split('.').pop().toLowerCase();
    if (!allowedExts.includes(ext)) {
        showToast(`不支持的文件格式: .${ext}，请上传 ${allowedExts.map(e => '.' + e).join('、')} 格式的文件`, 'warning');
        return;
    }

    // 暂存已选文件，再由确认弹窗决定直接上传或先去设置
    _deferredUpload = { kind: 'file', file };
    maybeConfirmSettings(doUploadDeferred);
}

// 直接执行上传（不再二次确认），供「确认弹窗」与「去设置后恢复」复用
function doUploadDeferred() {
    const d = _deferredUpload;
    _deferredUpload = null;
    if (!d) return;
    if (d.kind === 'file') {
        performFileUpload(d.file);
    } else if (d.kind === 'text') {
        performTextUpload(d.text);
    }
}

function performFileUpload(file) {
    showLoading(LOADING_STEPS_FILE, Math.round(file.size / 3));
    const formData = new FormData();
    formData.append('file', file);
    formData.append('scenario', selectedScenario);
    formData.append('enable_security', securityEnabled ? 'true' : 'false');
    formData.append('enable_sensitive', sensitiveEnabled ? 'true' : 'false');
    formData.append('enable_ad_extreme', adExtremeEnabled ? 'true' : 'false');
    const gj = getGlossaryJSON();
    const bj = getBannedWordsJSON();
    if (gj) formData.append('custom_glossary', gj);
    if (bj) formData.append('banned_words', bj);
    // 保存本次检查的术语数据，供"重新检查"复用
    _lastCheckGlossary = gj;
    _lastCheckBanned = bj;

    fetch('/api/analyze', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        onLoadingDataReceived(data, !!data.error);
    })
    .catch(err => {
        onLoadingDataReceived({ error: '请求失败: ' + err.message }, true);
    });
}

// ============================================================
// 文本分析
// ============================================================
const textInput = document.getElementById('textInput');
const textCharCount = document.getElementById('textCharCount');

textInput.addEventListener('input', () => {
    const val = textInput.value;
    const cnChars = (val.match(/[\u4e00-\u9fff]/g) || []).length;
    const enWords = (val.match(/[a-zA-Z]+(?:'[a-z]+)?/g) || []).length;
    if (cnChars >= enWords && cnChars > 0) {
        textCharCount.textContent = cnChars + ' 字';
    } else if (enWords > 0) {
        textCharCount.textContent = enWords + ' words';
    } else {
        textCharCount.textContent = '0 字';
    }
});

function analyzeText() {
    const text = textInput.value.trim();
    if (!text) {
        showToast('请输入需要检查的文本内容', 'warning');
        return;
    }

    // 暂存文本，再由确认弹窗决定直接上传或先去设置
    _deferredUpload = { kind: 'text', text };
    maybeConfirmSettings(doUploadDeferred);
}

function performTextUpload(text) {
    showLoading(LOADING_STEPS_TEXT, text.length);
    const formData = new FormData();
    formData.append('text', text);
    formData.append('scenario', selectedScenario);
    formData.append('enable_security', securityEnabled ? 'true' : 'false');
    formData.append('enable_sensitive', sensitiveEnabled ? 'true' : 'false');
    formData.append('enable_ad_extreme', adExtremeEnabled ? 'true' : 'false');
    const gj = getGlossaryJSON();
    const bj = getBannedWordsJSON();
    if (gj) formData.append('custom_glossary', gj);
    if (bj) formData.append('banned_words', bj);
    // 保存本次检查的术语数据，供"重新检查"复用
    _lastCheckGlossary = gj;
    _lastCheckBanned = bj;

    fetch('/api/analyze', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        onLoadingDataReceived(data, !!data.error);
    })
    .catch(err => {
        onLoadingDataReceived({ error: '请求失败: ' + err.message }, true);
    });
}

// ============================================================
// 加载状态（渐进式检查进度）
// ============================================================
function showLoading(steps, charCount) {
    loadingStepIdx = 0;
    loadingResult = null;
    loadingResultIsError = false;
    loadingStepsArr = steps;
    loadingTimer = null;

    // 根据文本长度估算每步延迟，让进度感更真实
    charCount = charCount || 0;
    const baseDelay = charCount > 5000 ? 820 : charCount > 1000 ? 620 : 460;
    const checkStepExtra = charCount > 5000 ? 200 : charCount > 1000 ? 120 : 60;

    const overlay = document.getElementById('loadingOverlay');
    const stepsEl = document.getElementById('loadingSteps');
    const subEl = document.getElementById('progressCardSub');
    if (subEl) subEl.textContent = '系统正在逐项扫描您的原文';

    stepsEl.innerHTML = steps.map((s, i) =>
        `<div class="progress-step" data-idx="${i}">
            <div class="progress-step-left">
                <span class="step-status-icon">${s.icon}</span>
                <span class="step-check-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>
                <span class="step-spinner-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 12a9 9 0 1 1-6.219-8.56" style="opacity:0.3"/><path d="M21 12a9 9 0 0 1-6.219-8.56"/></svg></span>
            </div>
            <span class="progress-step-text">${s.text}<span class="thinking-dots"></span></span>
        </div>`
    ).join('');

    overlay.style.display = 'flex';
    updateLoadingSteps();

    function nextStep() {
        if (loadingStepIdx < steps.length - 1) {
            loadingStepIdx++;
            updateLoadingSteps();
            // 检查类步骤（中间步骤）停留更久
            const isCheckStep = loadingStepIdx > 1 && loadingStepIdx < steps.length - 1;
            const delay = baseDelay + (isCheckStep ? checkStepExtra : 0) + Math.random() * 120;
            loadingTimer = setTimeout(nextStep, delay);
        } else {
            loadingTimer = null;
            checkLoadingComplete();
        }
    }

    // 第一步停留更久，让用户感知"上传成功"
    const firstDelay = baseDelay + 500 + Math.random() * 300;
    loadingTimer = setTimeout(nextStep, firstDelay);
}

function updateLoadingSteps() {
    const els = document.querySelectorAll('.progress-step');
    els.forEach((el, i) => {
        el.classList.toggle('active', i === loadingStepIdx);
        el.classList.toggle('done', i < loadingStepIdx);
    });
    // 更新进度条
    const progress = Math.round(((loadingStepIdx + 1) / loadingStepsArr.length) * 100);
    const bar = document.getElementById('progressBarFill');
    if (bar) bar.style.width = progress + '%';
}

function onLoadingDataReceived(data, isError) {
    loadingResult = data;
    loadingResultIsError = isError;

    // 如果 loading 序列已走完（timer 已清除），直接完成
    if (loadingTimer === null && loadingStepIdx >= loadingStepsArr.length - 1) {
        finishLoading();
    }
    // 否则等序列自然走完后在 checkLoadingComplete 中触发
}

function checkLoadingComplete() {
    // 序列走完，如果后端已返回结果则展示
    if (loadingResult !== null) {
        finishLoading();
    } else {
        // 后端尚未返回，更新提示让用户知道在等待
        const subEl = document.getElementById('progressCardSub');
        if (subEl) subEl.textContent = '正在汇总检查结果，请稍候…';
    }
}

function finishLoading() {
    if (loadingTimer) {
        clearTimeout(loadingTimer);
        loadingTimer = null;
    }

    // 标记所有步骤完成 + 进度条满
    document.querySelectorAll('.progress-step').forEach(el => {
        el.classList.add('done');
        el.classList.remove('active');
    });
    const bar = document.getElementById('progressBarFill');
    if (bar) bar.style.width = '100%';

    const data = loadingResult;
    const isError = loadingResultIsError;
    loadingResult = null;

    // 短暂延迟后展示结果，让用户感知到"检查完成"
    setTimeout(() => {
        document.getElementById('loadingOverlay').style.display = 'none';
        if (bar) bar.style.width = '0%';
        if (isError) {
            if (data && data.error) showToast(data.error, 'error');
        } else {
            showResult(data);
        }
    }, 600);
}

function hideLoading() {
    document.getElementById('loadingOverlay').style.display = 'none';
}

// ============================================================
// 结果展示
// ============================================================
function showResult(data) {
    currentResult = data;
    issueStates = {};
    previewMode = false;
    editMode = false;

    // 重置查找替换状态（新检查结果）
    findState = { query: '', caseSensitive: false, activeIndex: -1, matches: [], scrollAfterRender: false };
    userReplacements = {};
    const frPanel = document.getElementById('findReplacePanel');
    if (frPanel) frPanel.style.display = 'none';
    const frBtn = document.getElementById('findReplaceBtn');
    if (frBtn) frBtn.classList.remove('active');
    if (document.getElementById('frFind')) document.getElementById('frFind').value = '';
    if (document.getElementById('frReplace')) document.getElementById('frReplace').value = '';
    if (document.getElementById('frTip')) document.getElementById('frTip').textContent = '';

    // 确保编辑覆盖层隐藏、标注区显示
    document.getElementById('editArea').classList.remove('is-visible');
    document.getElementById('annotatedText').style.display = 'block';
    const editBtn = document.getElementById('editToggle');
    if (editBtn) {
        editBtn.classList.remove('active');
        editBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> 编辑原文`;
    }

    data.issues.forEach((_, idx) => { issueStates[idx] = 'pending'; });

    enterResultView();
    window._hasResult = true;

    renderStats(data);
    renderAnnotatedText(data);
    renderIssueList(data);
    updateActionToolbar();

    window.scrollTo(0, 0);
    saveSessionState();

    // 检查完成后清除术语表和禁用词库（不留到下一次检查任务）
    // 术语数据已保存在 _lastCheckGlossary/_lastCheckBanned 供"重新检查"复用
    let _usedGlossaryCount = 0, _usedBannedCount = 0;
    try { _usedGlossaryCount = _lastCheckGlossary ? JSON.parse(_lastCheckGlossary).length : 0; } catch (e) {}
    try { _usedBannedCount = _lastCheckBanned ? JSON.parse(_lastCheckBanned).length : 0; } catch (e) {}
    clearGlossaryAfterCheck();
    if (_usedGlossaryCount > 0 || _usedBannedCount > 0) {
        showGlossaryUsedHint(_usedGlossaryCount, _usedBannedCount);
    }
}

function showGlossaryUsedHint(glossaryCount, bannedCount) {
    const el = document.getElementById('glossaryUsedHint');
    if (!el) return;
    const parts = [];
    if (glossaryCount > 0) parts.push(glossaryCount + ' 条自定义术语');
    if (bannedCount > 0) parts.push(bannedCount + ' 条禁用词');
    el.innerHTML =
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="hint-icon">' +
        '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><circle cx="12" cy="8" r="0.5" fill="currentColor"/></svg>' +
        '<span>本次检查已使用 ' + parts.join('、') + '，检查完成后已自动清除，不影响后续检查任务。</span>' +
        '<button class="hint-close-btn" onclick="document.getElementById(\'glossaryUsedHint\').style.display=\'none\'" aria-label="关闭提示">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>';
    el.style.display = 'flex';
}

function renderStats(data) {
    const stats = data.stats;
    const summary = data.summary;
    const statsRow = document.getElementById('statsRow');

    const cards = [
        {
            key: 'count',
            label: stats.primary_label || '总字数',
            value: stats.primary_count || 0,
            icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>`
        },
        {
            key: 'issue',
            label: '发现问题',
            value: summary.total,
            highlight: summary.total > 0,
            icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`
        },
        {
            key: 'compliance',
            label: '合规风险',
            value: (data.issues || []).filter(i => (i.layer || TYPE_TO_LAYER[i.type] || 'discourse') === 'security').length,
            highlight: (data.issues || []).some(i => (i.layer || TYPE_TO_LAYER[i.type] || 'discourse') === 'security'),
            icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`
        },
    ];

    statsRow.innerHTML = cards.map(c => {
        const statusHtml = c.key === 'issue'
            ? `<span class="stat-status">
                ${c.highlight
                    ? `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>需注意`
                    : `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>无问题`
                }
               </span>`
            : '';
        return `
        <div class="stat-card stat-card-${c.key} ${c.highlight ? 'highlight' : ''}">
            <div class="stat-icon">${c.icon}</div>
            <div class="stat-body">
                <div class="stat-value">${c.value.toLocaleString()}</div>
                <div class="stat-label">${c.label}</div>
            </div>
            ${statusHtml}
        </div>
    `;
    }).join('');

    // 场景标签
    const scenario = data.scenario || 'general';
    const scenarioNames = {
        general: '通用文档', academic: '学术论文', business: '商务文档',
        legal: '法律文书', news: '新闻稿', technical: '技术文档',
    };
    const scenarioBadge = document.createElement('div');
    scenarioBadge.className = 'scenario-badge';
    scenarioBadge.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg><span>${scenarioNames[scenario] || scenario}</span>`;
    statsRow.appendChild(scenarioBadge);
}

// ============================================================
// 查找 / 替换
// ============================================================
function escapeRegExp(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 在当前 currentResult.text 上计算查找匹配（绝对位置）
function ensureFind() {
    findState.matches = [];
    const q = findState.query;
    if (!q || !currentResult) return;
    let re;
    try {
        re = new RegExp(escapeRegExp(q), findState.caseSensitive ? 'g' : 'gi');
    } catch (e) {
        return;
    }
    const text = currentResult.text;
    let m;
    while ((m = re.exec(text)) !== null) {
        findState.matches.push({ s: m.index, e: m.index + m[0].length });
        if (m.index === re.lastIndex) re.lastIndex++; // 防止零宽死循环
    }
    if (findState.activeIndex >= findState.matches.length) {
        findState.activeIndex = findState.matches.length - 1;
    }
}

// 将一段原始文本（segOffset 为本段在全文中的起始偏移）包裹查找高亮，返回 HTML。
// 匹配超出本段范围的部分会被裁剪，避免跨段匹配被截断显示。
function highlightFindInSegment(rawStr, segOffset) {
    if (!findState.query || !findState.matches.length) return escapeHtml(rawStr);
    const segStart = segOffset;
    const segEnd = segOffset + rawStr.length;
    const activeMatch = (findState.activeIndex >= 0 && findState.matches[findState.activeIndex])
        ? findState.matches[findState.activeIndex] : null;

    const hits = [];
    for (const mm of findState.matches) {
        const relStart = mm.s - segStart;
        const relEnd = mm.e - segStart;
        if (relEnd <= 0 || relStart >= rawStr.length) continue; // 完全在段外
        const s = Math.max(0, relStart);
        const e = Math.min(rawStr.length, relEnd);
        if (e <= s) continue;
        hits.push({ s, e, isActive: activeMatch && activeMatch.s === mm.s });
    }
    if (!hits.length) return escapeHtml(rawStr);

    let html = '';
    let cursor = 0;
    for (const h of hits) {
        html += escapeHtml(rawStr.substring(cursor, h.s));
        html += `<mark class="find-hit${h.isActive ? ' find-hit--active' : ''}">${escapeHtml(rawStr.substring(h.s, h.e))}</mark>`;
        cursor = h.e;
    }
    html += escapeHtml(rawStr.substring(cursor));
    return html;
}

// 打开/关闭查找替换面板
function toggleFindReplace() {
    const panel = document.getElementById('findReplacePanel');
    if (!panel) return;
    const willOpen = panel.style.display === 'none';
    panel.style.display = willOpen ? 'block' : 'none';
    document.getElementById('findReplaceBtn').classList.toggle('active', willOpen);
    if (willOpen) {
        // 查找基于 currentResult.text，预览模式下文本不一致，自动退出预览
        if (previewMode) togglePreview();
        const input = document.getElementById('frFind');
        input.value = findState.query;
        input.focus();
        ensureFind();
        renderAnnotatedText(currentResult);
        updateFindCount();
    } else {
        // 关闭时清除高亮
        findState.query = '';
        ensureFind();
        if (currentResult) renderAnnotatedText(currentResult);
    }
}

// 重新执行查找（查找框输入或区分大小写变化时调用）
function runFind() {
    findState.query = document.getElementById('frFind').value;
    findState.caseSensitive = document.getElementById('frCase').checked;
    findState.activeIndex = -1;
    ensureFind();
    if (findState.matches.length) findState.activeIndex = 0;
    if (currentResult) renderAnnotatedText(currentResult);
    updateFindCount();
    if (findState.query && findState.matches.length) {
        findState.scrollAfterRender = true;
    }
}

function updateFindCount() {
    const el = document.getElementById('frCount');
    if (!el) return;
    el.textContent = `${findState.matches.length ? (findState.activeIndex + 1) : 0} / ${findState.matches.length}`;
}

function findNext() {
    if (!findState.matches.length) { showToast('未找到匹配内容', 'info'); return; }
    findState.activeIndex = (findState.activeIndex + 1) % findState.matches.length;
    if (currentResult) renderAnnotatedText(currentResult);
    updateFindCount();
    findState.scrollAfterRender = true;
}

function findPrev() {
    if (!findState.matches.length) { showToast('未找到匹配内容', 'info'); return; }
    findState.activeIndex = (findState.activeIndex - 1 + findState.matches.length) % findState.matches.length;
    if (currentResult) renderAnnotatedText(currentResult);
    updateFindCount();
    findState.scrollAfterRender = true;
}

// 将当前 active 匹配在 currentResult.text 中替换为目标串，并记录到 userReplacements
function _applyReplaceAt(activeIdx, replaceStr) {
    const m = findState.matches[activeIdx];
    if (!m) return false;
    currentResult.text = currentResult.text.slice(0, m.s) + replaceStr + currentResult.text.slice(m.e);
    userReplacements[findState.query] = replaceStr; // 供文件模式导出（重复键去重）
    currentResult._pendingRecheck = true; // 原文已变，旧 issue 位置失效
    return true;
}

function replaceCurrent() {
    if (!currentResult) return;
    if (!findState.query) { showToast('请先输入查找内容', 'info'); return; }
    ensureFind();
    if (!findState.matches.length) { showToast('未找到匹配内容', 'info'); return; }
    if (findState.activeIndex < 0) findState.activeIndex = 0;
    const replaceStr = document.getElementById('frReplace').value;
    _applyReplaceAt(findState.activeIndex, replaceStr);
    // 文本已变，重新计算匹配；删除一条后原 activeIndex 恰好指向"下一条"
    ensureFind();
    if (findState.activeIndex >= findState.matches.length) findState.activeIndex = findState.matches.length - 1;
    renderAnnotatedText(currentResult);
    updateFindCount();
    if (findState.matches.length) findState.scrollAfterRender = true;
    const tip = document.getElementById('frTip');
    if (tip) tip.textContent = `已替换 1 处`;
}

function replaceAll() {
    if (!currentResult) return;
    if (!findState.query) { showToast('请先输入查找内容', 'info'); return; }
    ensureFind();
    const total = findState.matches.length;
    if (!total) { showToast('未找到匹配内容', 'info'); return; }
    const replaceStr = document.getElementById('frReplace').value;
    // 一次性全局替换（从后往前避免偏移）
    for (let i = findState.matches.length - 1; i >= 0; i--) {
        const m = findState.matches[i];
        currentResult.text = currentResult.text.slice(0, m.s) + replaceStr + currentResult.text.slice(m.e);
    }
    userReplacements[findState.query] = replaceStr;
    currentResult._pendingRecheck = true;
    findState.activeIndex = -1;
    ensureFind();
    renderAnnotatedText(currentResult);
    updateFindCount();
    const tip = document.getElementById('frTip');
    if (tip) tip.textContent = `已替换全部 ${total} 处`;
    showToast(`已替换全部 ${total} 处`, 'success');
}

function clearFind() {
    const f = document.getElementById('frFind');
    const r = document.getElementById('frReplace');
    if (f) f.value = '';
    if (r) r.value = '';
    const tip = document.getElementById('frTip');
    if (tip) tip.textContent = '';
    findState.query = '';
    findState.activeIndex = -1;
    ensureFind();
    if (currentResult) renderAnnotatedText(currentResult);
    updateFindCount();
}

// 渲染完成后滚动到当前 active 匹配
function scrollToActiveFind() {
    if (!findState.scrollAfterRender) return;
    findState.scrollAfterRender = false;
    if (findState.activeIndex < 0) return;
    const el = document.querySelector('#annotatedText .find-hit--active');
    if (el) {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        el.classList.add('find-hit--flash');
        setTimeout(() => el.classList.remove('find-hit--flash'), 700);
    }
}

// 查找框键盘：Enter 下一个，Shift+Enter 上一个
function onFrFindKey(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey) findPrev(); else findNext();
    }
}

// ============================================================
// 标注文本渲染
// ============================================================
// ============================================================
// 句段切分与句段视图渲染
// ============================================================

const SEG_VIEW_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg> ';

/**
 * 将文本按句子切分为句段（一句一行），返回 [{ text, start, end }]。
 * start/end 为句段在原文中的绝对字符偏移，便于与问题 position 对齐、双击定位光标。
 * 处理要点：中英文句号/叹号/问号 + 换行作为边界；排除英文缩写(Mr./Dr./etc.)、
 * 小数(3.14)、省略号(...)；句末闭合引号/括号并入当前句段。
 */
function splitSentences(text) {
    const out = [];
    if (!text) return out;
    const n = text.length;
    const ABBR = new Set([
        'mr', 'mrs', 'ms', 'dr', 'prof', 'st', 'vs', 'etc', 'no', 'eg', 'ie', 'approx',
        'inc', 'ltd', 'co', 'corp', 'sr', 'jr', 'fig', 'eq', 'al', 'vol', 'chap', 'sec',
        'gen', 'sen', 'rep', 'gov', 'pres', 'capt', 'lt', 'sgt', 'col', 'maj', 'rev',
        'hon', 'phd', 'md', 'ba', 'bs', 'dept', 'univ', 'est', 'assn', 'bros', 'prod',
        'tech', 'eng', 'nos',
    ]);
    function isRealSentenceEnd(idx) {
        const c = text[idx];
        if (c === '\n') return true;
        if (c === '。' || c === '！' || c === '？' || c === '!' || c === '?') return true;
        if (c === '.') {
            // 省略号：前后也是 '.' 或 '…'
            if (idx > 0 && text[idx - 1] === '.') return false;
            if (idx < n - 1 && text[idx + 1] === '.') return false;
            if (idx > 0 && text[idx - 1] === '…') return false;
            if (idx < n - 1 && text[idx + 1] === '…') return false;
            // 小数点后跟数字 → 小数，非句末
            if (idx < n - 1 && /[0-9]/.test(text[idx + 1])) return false;
            // 已知缩写（Mr./Dr./etc./Inc./No. ...）
            let j = idx - 1;
            while (j >= 0 && /[A-Za-z]/.test(text[j])) j--;
            const word = text.substring(j + 1, idx).toLowerCase();
            if (ABBR.has(word)) return false;
            // 缩写粘连：句点后无空白（如 "Inc." 紧跟其他内容）
            if (idx < n - 1 && !/\s/.test(text[idx + 1])) return false;
            // 单字母 + 前一字符也是句点（x.y. 型缩写，如 U.S. / e.g. 的第二句点）
            if (/[A-Za-z]/.test(text[idx - 1] || '') && idx >= 2 && text[idx - 2] === '.') return false;
            return true;
        }
        return false;
    }
    let i = 0;
    while (i < n) {
        while (i < n && /\s/.test(text[i])) i++;
        if (i >= n) break;
        const segStart = i;
        let end = -1;
        while (i < n) {
            if (isRealSentenceEnd(i)) {
                // 吞掉句末闭合引号/括号，使其并入当前句段
                let k = i + 1;
                while (k < n && /[”’」』）】》"')}\]]/.test(text[k])) k++;
                end = k;
                break;
            }
            i++;
        }
        if (end === -1) end = n; // 无句末符，整段作为一句
        const segText = text.substring(segStart, end).replace(/\s+$/, '');
        if (segText.trim().length > 0) {
            out.push({ text: segText, start: segStart, end: end });
        }
        i = end;
    }
    return out;
}

/**
 * 根据绝对字符偏移 position 反查其在句段视图中的行号（1 起始）。
 * 用于让右侧问题卡片的"定位数字"指向原文第几行，而非段落。
 */
function lineOfPosition(text, pos) {
    const segs = splitSentences(text || '');
    for (let i = 0; i < segs.length; i++) {
        if (pos >= segs[i].start && pos < segs[i].end) return i + 1;
    }
    if (segs.length && pos >= segs[segs.length - 1].end) return segs.length;
    return segs.length ? 1 : 0;
}

/**
 * 渲染 [rangeStart, rangeEnd) 区间的文本，叠加问题高亮与查找高亮。
 * 问题与查找匹配均使用全文绝对偏移，故句段视图与连续视图共用此函数。
 */
function renderHighlightedRange(text, rangeStart, rangeEnd, issues) {
    const inRange = issues.map((issue, idx) => ({ ...issue, _idx: idx }))
        .filter((iss) => iss.end_position > rangeStart && iss.position < rangeEnd)
        .sort((a, b) => a.position - b.position || a.end_position - b.end_position);

    let result = '';
    let lastEnd = rangeStart;

    for (const issue of inRange) {
        const start = Math.max(issue.position, rangeStart);
        const end = Math.min(issue.end_position, rangeEnd);
        if (start < 0 || end > text.length || start >= end) continue;

        if (start < lastEnd) {
            if (end <= lastEnd) continue;
            const overlapOriginal = text.substring(lastEnd, end);
            const overlapIssueId = `issue-${issue.position}-${issue.end_position}`;
            result += buildHighlightSpan({ ...issue, _idx: issue._idx }, overlapIssueId, overlapOriginal);
            lastEnd = end;
            continue;
        }

        if (start > lastEnd) {
            result += highlightFindInSegment(text.substring(lastEnd, start), lastEnd);
        }

        const issueId = `issue-${issue.position}-${issue.end_position}`;
        const original = text.substring(start, end);
        result += buildHighlightSpan(issue, issueId, original);
        lastEnd = end;
    }

    if (lastEnd < rangeEnd) {
        result += highlightFindInSegment(text.substring(lastEnd, rangeEnd), lastEnd);
    }
    return result;
}

function segRowHtml(gutter, contentHtml, segStart) {
    return `<div class="seg-row"><div class="seg-gutter">${gutter}</div>`
        + `<div class="seg-content" data-seg-start="${segStart}">${contentHtml}</div></div>`;
}

function dblHintHtml() {
    return '<div class="dblclick-hint">双击可编辑原文</div>';
}

/** 双击原文进入编辑模式，并定位光标到双击位置（兼容句段视图与连续视图）。 */
function handleAnnotatedDblClick(e) {
    if (editMode || previewMode) return;
    const container = document.getElementById('annotatedText');
    if (!container) return;
    let contentEl, segStart;
    if (segView) {
        contentEl = e.target.closest('.seg-content');
        if (!contentEl) return; // 点到行号栏等，忽略
        segStart = parseInt(contentEl.getAttribute('data-seg-start') || '0', 10) || 0;
    } else {
        contentEl = container;
        segStart = 0;
    }
    const rel = getCaretOffsetFromEvent(e, contentEl);
    if (rel < 0) return;
    toggleEdit(segStart + rel);
}

/** 切换句段视图 / 连续视图。 */
function toggleSegView() {
    segView = !segView;
    const btn = document.getElementById('segViewToggle');
    if (btn) {
        btn.classList.toggle('active', segView);
        btn.innerHTML = SEG_VIEW_ICON + (segView ? '句段视图' : '连续视图');
    }
    if (currentResult) renderAnnotatedText(currentResult);
}

function renderAnnotatedText(data) {
    const container = document.getElementById('annotatedText');
    const text = data.text;
    const issues = data.issues || [];

    // 查找高亮基于 currentResult.text（与预览文本不同源），预览模式不渲染查找高亮
    if (findState.query && !previewMode) ensureFind();

    // 修改预览模式：显示修改后的纯文本（按句切分、带行号）
    if (previewMode) {
        const modified = getModifiedText();
        const segs = splitSentences(modified);
        let html = '<div class="seg-list">';
        segs.forEach((seg, i) => {
            html += segRowHtml(i + 1, escapeHtml(seg.text), seg.start);
        });
        html += '</div>';
        container.innerHTML = html + dblHintHtml();
        container.ondblclick = handleAnnotatedDblClick;
        scrollToActiveFind();
        return;
    }

    // 原文刚被编辑过：旧问题位置可能失效，仅显示纯文本（句段/连续均可）
    if (data._pendingRecheck) {
        if (segView) {
            const segs = splitSentences(text);
            let html = '<div class="seg-list">';
            segs.forEach((seg, i) => {
                html += segRowHtml(i + 1, highlightFindInSegment(seg.text, seg.start), seg.start);
            });
            html += '</div>';
            container.innerHTML = html + dblHintHtml();
        } else {
            container.innerHTML = highlightFindInSegment(text, 0) + dblHintHtml();
        }
        container.ondblclick = handleAnnotatedDblClick;
        scrollToActiveFind();
        return;
    }

    // 句段视图（默认）：一句一行 + 行号，句内按问题区间叠加高亮
    if (segView) {
        const segs = splitSentences(text);
        let html = '<div class="seg-list">';
        segs.forEach((seg, i) => {
            const content = renderHighlightedRange(text, seg.start, seg.end, issues);
            html += segRowHtml(i + 1, content, seg.start);
        });
        html += '</div>';
        container.innerHTML = html + dblHintHtml();
        container.ondblclick = handleAnnotatedDblClick;
        scrollToActiveFind();
        return;
    }

    // 连续视图（句段视图关闭）：保持原有整段渲染逻辑
    const sortedIssues = [...issues].map((issue, idx) => ({ ...issue, _idx: idx }))
        .sort((a, b) => a.position - b.position || a.end_position - b.end_position);

    let result = '';
    let lastEnd = 0;

    for (const issue of sortedIssues) {
        const start = issue.position;
        const end = issue.end_position;

        if (start < 0 || end > text.length || start >= end) continue;

        if (start < lastEnd) {
            if (end <= lastEnd) continue;
            const overlapOriginal = text.substring(lastEnd, end);
            const overlapIssueId = `issue-${issue.position}-${issue.end_position}`;
            result += buildHighlightSpan(issue, overlapIssueId, overlapOriginal);
            lastEnd = end;
            continue;
        }

        if (start > lastEnd) {
            result += highlightFindInSegment(text.substring(lastEnd, start), lastEnd);
        }

        const issueId = `issue-${issue.position}-${issue.end_position}`;
        const original = text.substring(start, end);
        result += buildHighlightSpan(issue, issueId, original);
        lastEnd = end;
    }

    if (lastEnd < text.length) {
        result += highlightFindInSegment(text.substring(lastEnd), lastEnd);
    }

    container.innerHTML = result + dblHintHtml();
    container.ondblclick = handleAnnotatedDblClick;
    scrollToActiveFind();
}


/**
 * 根据鼠标事件计算在原文纯文本中的字符偏移量。
 * 通过遍历容器的文本节点，累加长度直到找到点击位置。
 */
function getCaretOffsetFromEvent(e, container) {
    try {
        const range = document.caretRangeFromPoint(e.clientX, e.clientY);
        if (!range) return -1;
        // 确保 range 在 container 内
        if (!container.contains(range.startContainer)) return -1;
        // 遍历所有文本节点累加偏移
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
        let offset = 0;
        let node;
        while ((node = walker.nextNode())) {
            if (node === range.startContainer) {
                return offset + range.startOffset;
            }
            offset += node.textContent.length;
        }
        return -1;
    } catch (err) {
        return -1;
    }
}

function buildHighlightSpan(issue, issueId, original) {
    const state = issueStates[issue._idx] || 'pending';

    if (state === 'accepted') {
        // 只有具体替换内容才替换原文显示；建议性说明（如"（建议…）"）仍显示原文
        if (isRealSuggestion(issue)) {
            // 增量修订：仅高亮被改动的字符，而非整段替换
            const html = inlineDiffHtml(original, issue.suggestion || '');
            return `<span class="issue-accepted-diff" data-issue-id="${issueId}" onclick="scrollToIssue('${issueId}')" title="${escapeHtml(issue.description)}">${html}</span>`;
        }
        return highlightFindInSegment(original, issue.position);
    } else if (state === 'rejected') {
        // 忽略的问题：取消标记，恢复为普通原文（无高亮、无下划线）
        return highlightFindInSegment(original, issue.position);
    } else {
        return `<span class="issue-highlight severity-${issue.severity}" data-issue-id="${issueId}" onclick="scrollToIssue('${issueId}')" title="${escapeHtml(issue.description)}">${highlightFindInSegment(original, issue.position)}</span>`;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 将空白内容渲染为可视化占位，避免 diff 行看起来为空
function formatDiffText(text, fallbackLabel) {
    if (text === undefined || text === null) {
        return fallbackLabel ? escapeHtml(fallbackLabel) : '<span class="diff-empty">（无）</span>';
    }
    // 仅空白字符：用带计数的描述性标签展示
    if (/^\s+$/.test(text)) {
        const count = text.length;
        let label;
        if (count === 1) {
            label = '一个空格';
        } else if (count === 2) {
            label = '两个空格';
        } else {
            label = `多个空格（${count}个）`;
        }
        return `<span class="diff-whitespace" title="连续 ${count} 个空格">${escapeHtml(label)}</span>`;
    }
    return escapeHtml(text);
}

// 轻量 escape：避免 inlineDiff 高频调用 DOM 版 escapeHtml 的性能开销
function escapeText(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// 字符级 LCS 差异，输出"仅体现变动处"的内联修订 HTML：
// 未改动部分正常显示，删除部分用 <del>，新增部分用 <ins>。
// 这样接受修改时不会整段替换，而是只高亮被改动的几个字。
function inlineDiffHtml(orig, sugg) {
    if (orig === undefined || orig === null) orig = '';
    if (sugg === undefined || sugg === null) sugg = '';
    if (orig === sugg) return escapeText(orig);

    const n = orig.length, m = sugg.length;
    const MAX = 4000;
    if (n > MAX || m > MAX) {
        // 超长降级：整体显示为删+增
        return `<del class="diff-del">${escapeText(orig)}</del><ins class="diff-ins">${escapeText(sugg)}</ins>`;
    }

    // LCS 长度 DP（压缩为一维滚动数组以省内存）
    const dp = new Array((n + 1) * (m + 1)).fill(0);
    const idx = (i, j) => i * (m + 1) + j;
    for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
            if (orig[i] === sugg[j]) dp[idx(i, j)] = dp[idx(i + 1, j + 1)] + 1;
            else dp[idx(i, j)] = Math.max(dp[idx(i + 1, j)], dp[idx(i, j + 1)]);
        }
    }

    let i = 0, j = 0;
    let html = '';
    let bufEq = '', bufDel = '', bufIns = '';
    const flush = () => {
        if (bufEq) { html += escapeText(bufEq); bufEq = ''; }
        if (bufDel) { html += `<del class="diff-del">${escapeText(bufDel)}</del>`; bufDel = ''; }
        if (bufIns) { html += `<ins class="diff-ins">${escapeText(bufIns)}</ins>`; bufIns = ''; }
    };
    while (i < n && j < m) {
        if (orig[i] === sugg[j]) {
            flush();
            bufEq += orig[i]; i++; j++;
        } else if (dp[idx(i + 1, j)] >= dp[idx(i, j + 1)]) {
            bufDel += orig[i]; i++;
        } else {
            bufIns += sugg[j]; j++;
        }
    }
    while (i < n) { bufDel += orig[i]; i++; }
    while (j < m) { bufIns += sugg[j]; j++; }
    flush();
    return html;
}

// ============================================================
// 问题列表渲染
// ============================================================
function renderIssueList(data) {
    const container = document.getElementById('issueList');
    const issues = data.issues;
    const displayIndices = issues.map((_, idx) => idx);

    document.getElementById('issueCount').textContent = `${issues.length} 个问题`;

    if (issues.length === 0) {
        const isPendingRecheck = data._pendingRecheck;
        container.innerHTML = `
            <div class="empty-state">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    ${isPendingRecheck
                        ? '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>'
                        : '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'}
                </svg>
                <h3>${isPendingRecheck ? '原文已修改' : '没有问题'}</h3>
                <p>${isPendingRecheck ? '点击右上角「重新检查」可重新扫描修改后的原文' : '当前筛选条件下未发现问题'}</p>
            </div>
        `;
        return;
    }

    // 原文已修改提示横幅
    const staleWarning = data._pendingRecheck
        ? `<div class="stale-warning"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> 原文已修改，以下问题基于修改前的原文，位置可能不准确；建议点击右上角「重新检查」刷新。</div>`
        : '';

    container.innerHTML = staleWarning + issues.map((issue, displayIdx) => {
        const originalIdx = displayIndices[displayIdx];
        const state = issueStates[originalIdx] || 'pending';
        const issueId = `issue-${issue.position}-${issue.end_position}`;
        const lineNo = lineOfPosition(data.text || '', issue.position);

        let actionButtons = '';
        if (state === 'pending') {
            actionButtons = `
                <button class="action-icon accept-icon" title="接受修改" onclick="event.stopPropagation(); acceptIssue(${originalIdx})">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                </button>
                <button class="action-icon reject-icon" title="忽略" onclick="event.stopPropagation(); rejectIssue(${originalIdx})">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            `;
        } else if (state === 'accepted') {
            actionButtons = `
                <span class="action-state state-accepted">已接受</span>
                <button class="action-icon undo-icon" title="撤销" onclick="event.stopPropagation(); undoIssue(${originalIdx})">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>
                </button>
            `;
        } else {
            actionButtons = `
                <span class="action-state state-rejected">已忽略</span>
                <button class="action-icon undo-icon" title="撤销" onclick="event.stopPropagation(); undoIssue(${originalIdx})">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>
                </button>
            `;
        }

        // 改写方案区域：仅对 pending 状态且存在 alternatives 的问题显示
        let alternativesHtml = '';
        if (state === 'pending' && issue.alternatives && issue.alternatives.length > 1) {
            const currentSuggestion = issue.suggestion || '';
            const selectedIdx = issue.alternatives.indexOf(currentSuggestion);
            alternativesHtml = `
                <div class="issue-alternatives">
                    <div class="alternatives-label">选择修改方案</div>
                    <div class="alternatives-list">
                        ${issue.alternatives.map((alt, altIdx) => `
                            <button class="alternative-btn ${altIdx === selectedIdx ? 'selected' : ''}"
                                    onclick="event.stopPropagation(); selectAlternative(${originalIdx}, ${altIdx})"
                                    title="选择方案 ${altIdx + 1}">
                                <span class="alternative-radio"></span>
                                <span class="alternative-text">${escapeHtml(alt)}</span>
                                ${altIdx === 0 ? '<span class="alternative-badge">推荐</span>' : ''}
                            </button>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        const layerKey = TYPE_TO_LAYER[issue.type] || 'discourse';
        const layerName = LAYER_NAMES[layerKey] || '';

        // 构建"改为"行：仅当有具体替换内容（含空字符串=删除）时才显示
        let suggestionRowHtml = '';
        if (isRealSuggestion(issue) || issue.suggestion === '') {
            // 用内联差异展示，仅标出变动处（删除=删去的字，新增=改后的字）
            const diffHtml = inlineDiffHtml(issue.original || '', issue.suggestion || '');
            suggestionRowHtml = `
                        <div class="diff-row diff-suggestion">
                            <span class="diff-label">改为</span>
                            <span class="diff-text">${diffHtml}</span>
                        </div>`;
        }

        // 清理描述文本：移除冗余的"建议改为「…」"（"改为"行已展示），
        // 并将建议性 suggestion 合并到描述
        let descText = issue.description || '';
        descText = descText.replace(/，?\s*建议(?:改为|补全为)[^」]*」/g, '');
        if (!isRealSuggestion(issue) && issue.suggestion) {
            descText = descText ? `${descText}。${issue.suggestion}` : issue.suggestion;
        }
        const descHtml = descText ? `
                    <div class="issue-desc">
                        <span class="desc-label">说明</span>
                        <span class="desc-text">${escapeHtml(descText)}</span>
                    </div>` : '';

        return `
            <div class="issue-card state-${state} layer-${layerKey}" id="card-${issueId}" onclick="scrollToHighlight('${issueId}')">
                <div class="issue-card-body">
                    <div class="issue-meta">
                        <span class="issue-index">#${displayIdx + 1}</span>
                        <span class="issue-line" title="对应原文行号">第 ${lineNo} 行</span>
                        <span class="issue-severity severity-${issue.severity}" title="${issue.severity === 'error' ? '错误' : issue.severity === 'warning' ? '警告' : '建议'}"></span>
                        <span class="issue-layer">${layerName}</span>
                        <span class="issue-type">${TYPE_LABELS[issue.type] || issue.type}</span>
                    </div>
                    <div class="issue-diff">
                        <div class="diff-row diff-original">
                            <span class="diff-label">原文</span>
                            <span class="diff-text">${formatDiffText(issue.original)}</span>
                        </div>
                        ${suggestionRowHtml}
                    </div>
                    ${descHtml}
                    ${issue.context ? `<div class="issue-context">${escapeHtml(issue.context)}</div>` : ''}
                    ${alternativesHtml}
                </div>
                <div class="issue-actions">${actionButtons}</div>
            </div>
        `;
    }).join('');
}

// ============================================================
// 接受 / 忽略 / 撤销
// ============================================================
function selectAlternative(idx, altIdx) {
    if (!currentResult || !currentResult.issues[idx]) return;
    const issue = currentResult.issues[idx];
    if (!issue.alternatives || altIdx < 0 || altIdx >= issue.alternatives.length) return;

    issue.suggestion = issue.alternatives[altIdx];
    renderIssueList(currentResult);
    updateActionToolbar();
    saveSessionState();
}

function acceptIssue(idx) {
    issueStates[idx] = 'accepted';
    renderIssueList(currentResult);
    renderAnnotatedText(currentResult);
    updateActionToolbar();
    saveSessionState();
}

function rejectIssue(idx) {
    issueStates[idx] = 'rejected';
    renderIssueList(currentResult);
    renderAnnotatedText(currentResult);
    updateActionToolbar();
    saveSessionState();
}

function undoIssue(idx) {
    issueStates[idx] = 'pending';
    renderIssueList(currentResult);
    renderAnnotatedText(currentResult);
    updateActionToolbar();
    saveSessionState();
}

// 获取所有仍为待处理的问题索引，用于批量接受/忽略。
function getPendingIndices() {
    if (!currentResult) return [];
    const out = [];
    currentResult.issues.forEach((issue, idx) => {
        if (issueStates[idx] === 'pending') out.push(idx);
    });
    return out;
}

function acceptAll() {
    // 对所有仍为待处理的问题生效
    const indices = getPendingIndices();
    if (!indices.length) return;
    // 保存快照供撤销
    lastBatchSnapshot = JSON.parse(JSON.stringify(issueStates));

    indices.forEach(idx => { issueStates[idx] = 'accepted'; });
    renderIssueList(currentResult);
    renderAnnotatedText(currentResult);
    updateActionToolbar();
    saveSessionState();
    showBatchUndoToast('批量接受', indices.length);
}

function rejectAll() {
    // 对所有仍为待处理的问题生效
    const indices = getPendingIndices();
    if (!indices.length) return;
    lastBatchSnapshot = JSON.parse(JSON.stringify(issueStates));

    indices.forEach(idx => { issueStates[idx] = 'rejected'; });
    renderIssueList(currentResult);
    renderAnnotatedText(currentResult);
    updateActionToolbar();
    saveSessionState();
    showBatchUndoToast('批量忽略', indices.length);
}

// ============================================================
// 批量操作撤销
// ============================================================
function showBatchUndoToast(actionLabel, count) {
    // 移除已有 Toast
    hideBatchUndoToast();

    const toast = document.createElement('div');
    toast.id = 'batchUndoToast';
    toast.className = 'batch-undo-toast';
    toast.innerHTML = `
        <span class="batch-undo-text">${actionLabel}已应用 ${count} 条${scope}</span>
        <button class="batch-undo-btn" onclick="undoBatchAction()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>
            撤销
        </button>
    `;
    document.body.appendChild(toast);

    // 动画进入
    requestAnimationFrame(() => toast.classList.add('show'));

    // 30 秒后自动消失
    batchUndoTimer = setTimeout(() => {
        hideBatchUndoToast();
        lastBatchSnapshot = null;
    }, 30000);
}

function hideBatchUndoToast() {
    const toast = document.getElementById('batchUndoToast');
    if (toast) {
        toast.classList.remove('show');
        setTimeout(() => { if (toast.parentNode) toast.remove(); }, 300);
    }
    if (batchUndoTimer) {
        clearTimeout(batchUndoTimer);
        batchUndoTimer = null;
    }
}

function undoBatchAction() {
    if (!lastBatchSnapshot) return;
    issueStates = lastBatchSnapshot;
    lastBatchSnapshot = null;
    hideBatchUndoToast();

    renderIssueList(currentResult);
    renderAnnotatedText(currentResult);
    updateActionToolbar();
    saveSessionState();
}

// ============================================================
// 工具栏状态更新
// ============================================================
// 与后端 Word「字数」口径近似对齐：
// 中文字符（CJK 汉字、CJK 标点、全角符号、中文引号、破折号、省略号等）
// + 英文单词 + 数字串。空白、半角标点不计入。
function countWordsLikeWord(text) {
    const cjkPattern = /[\u{3400}-\u{4DBF}\u{4E00}-\u{9FFF}\u{F900}-\u{FAFF}\u{3007}\u{3000}-\u{303F}\u{FF00}-\u{FFEF}\u{2018}\u{2019}\u{201C}\u{201D}\u{2014}\u{2026}\u{00B7}]/gu;
    const cjk = (text.match(cjkPattern) || []).length;
    const en = (text.match(/[a-zA-Z]+(?:['\-][a-zA-Z]+)*/g) || []).length;
    const num = (text.match(/\d+(?:[.,]\d+)*/g) || []).length;
    return cjk + en + num;
}

// 判断 suggestion 是否为可直接替换原文的具体修改内容。
// 建议性说明（如"（建议统一使用中文数字或阿拉伯数字）"）不是具体替换内容，
// 不应直接插入到原文中，仅作为问题说明展示。
function isRealSuggestion(issue) {
    return issue.suggestion && !issue.suggestion.startsWith('（建议');
}

function updateActionToolbar() {
    const values = Object.values(issueStates);
    const accepted = values.filter(s => s === 'accepted').length;
    const rejected = values.filter(s => s === 'rejected').length;
    const total = values.length;
    const pending = total - accepted - rejected;

    document.getElementById('acceptedCount').textContent = accepted;
    document.getElementById('rejectedCount').textContent = rejected;
    document.getElementById('pendingCount').textContent = pending;

    // 批量操作按钮：按「当前筛选范围」计算可批量处理的数量（按类型批量接受/忽略）
    const pendingCount = getPendingIndices().length;
    const acceptAllBtn = document.getElementById('acceptAllBtn');
    const rejectAllBtn = document.getElementById('rejectAllBtn');
    if (acceptAllBtn) {
        acceptAllBtn.disabled = pendingCount === 0;
        const lbl = document.getElementById('acceptAllLabel');
        if (lbl) lbl.textContent = pendingCount > 0 ? `接受全部 ${pendingCount} 条` : '接受全部';
    }
    if (rejectAllBtn) {
        rejectAllBtn.disabled = pendingCount === 0;
        const lbl = document.getElementById('rejectAllLabel');
        if (lbl) lbl.textContent = pendingCount > 0 ? `忽略全部 ${pendingCount} 条` : '忽略全部';
    }
}

// ============================================================
// 原文编辑模式
// ============================================================

/**
 * 将原文标注区的实际计算样式同步到编辑 textarea，
 * 确保字体、行高、字距、padding 等完全一致，切换时无视觉跳动。
 */
function applyEditorStylesFromDisplay() {
    const annotated = document.getElementById('annotatedText');
    const textarea = document.getElementById('editTextarea');
    if (!annotated || !textarea) return;

    const computed = window.getComputedStyle(annotated);
    const styleProps = [
        'font-family', 'font-size', 'font-weight', 'line-height',
        'letter-spacing', 'word-spacing', 'text-align', 'text-indent',
        'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
        'white-space', 'word-break', 'overflow-wrap', 'tab-size', 'color'
    ];

    styleProps.forEach(prop => {
        textarea.style.setProperty(prop, computed.getPropertyValue(prop));
    });
}

function toggleEdit(caretPos) {
    if (editMode) {
        cancelEdit();
        return;
    }
    // 进入编辑模式
    editMode = true;
    previewMode = false;

    // 更新按钮状态
    const editBtn = document.getElementById('editToggle');
    if (editBtn) {
        editBtn.classList.add('active');
        editBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> 退出编辑`;
    }
    const previewBtn = document.getElementById('previewToggle');
    if (previewBtn) {
        previewBtn.classList.remove('active');
        previewBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg> 修改预览`;
    }

    // 在任何 DOM 变更前保存滚动位置
    const panelBody = document.querySelector('.panel-body--editor');
    const savedScrollTop = panelBody ? panelBody.scrollTop : 0;

    // 获取当前文本（含已接受的修改）
    const currentText = getModifiedText();
    const textarea = document.getElementById('editTextarea');
    textarea.value = currentText;

    // 同步标注区样式，确保编辑框与原文显示完全一致（需在隐藏前读取）
    applyEditorStylesFromDisplay();

    // 隐藏原文标注区，编辑区直接替换其位置，避免上下两部分
    document.getElementById('annotatedText').style.display = 'none';

    // 显示编辑区
    document.getElementById('editArea').classList.add('is-visible');

    // 使用 preventScroll 避免 focus 自动滚动到光标位置
    try { textarea.focus({ preventScroll: true }); } catch(e) { textarea.focus(); }

    // 设置光标位置（同步执行，避免延迟导致的跳动）
    if (typeof caretPos === 'number' && caretPos >= 0) {
        try {
            const pos = Math.min(caretPos, textarea.value.length);
            textarea.setSelectionRange(pos, pos);
        } catch (err) { /* ignore */ }
    }

    // 恢复滚动位置（必须在 setSelectionRange 之后，否则浏览器会自动滚动到光标处）
    textarea.scrollTop = savedScrollTop;
    if (panelBody) panelBody.scrollTop = savedScrollTop;
}

function cancelEdit() {
    editMode = false;
    const editBtn = document.getElementById('editToggle');
    if (editBtn) {
        editBtn.classList.remove('active');
        editBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> 编辑原文`;
    }
    document.getElementById('editArea').classList.remove('is-visible');
    document.getElementById('annotatedText').style.display = 'block';
}

function saveEdit() {
    const editedText = document.getElementById('editTextarea').value.trim();
    if (!editedText) {
        showToast('原文内容不能为空', 'warning');
        return;
    }

    // 检查是否有实际变化
    const currentText = getModifiedText();
    if (editedText === currentText) {
        showToast('原文内容未修改', 'warning');
        return;
    }

    // 保存编辑后的文本，但保留原有问题列表与处理状态，方便用户继续审阅
    currentResult.text = editedText;
    currentResult._pendingRecheck = true; // 标记：原文已修改，旧问题位置可能不准确
    // 保留 currentResult.issues 和 issueStates，不重置 summary
    // 仅更新基础统计（字数/段落数），采用 Word 字数口径
    currentResult.stats = {
        primary_label: '总字数',
        primary_count: countWordsLikeWord(editedText),
        paragraph_count: editedText.trim() ? (editedText.trim().match(/\n/g) || []).length + 1 : 0
    };

    // 退出编辑模式
    editMode = false;
    document.getElementById('editArea').classList.remove('is-visible');
    document.getElementById('annotatedText').style.display = 'block';
    const editBtn = document.getElementById('editToggle');
    if (editBtn) {
        editBtn.classList.remove('active');
        editBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> 编辑原文`;
    }

    // 重新渲染审阅页面（不调用 API 重新检查）
    renderStats(currentResult);
    renderAnnotatedText(currentResult);
    renderIssueList(currentResult);
    updateActionToolbar();
    saveSessionState();
}

// ============================================================
// 修改预览切换
// ============================================================
function togglePreview() {
    // 如果在编辑模式，先退出
    if (editMode) cancelEdit();
    previewMode = !previewMode;
    const btn = document.getElementById('previewToggle');
    if (btn) {
        if (previewMode) {
            btn.classList.add('active');
            btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg> 查看标注`;
        } else {
            btn.classList.remove('active');
            btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg> 修改预览`;
        }
    }
    renderAnnotatedText(currentResult);
}

// ============================================================
// 获取修改后的文本
// ============================================================
function getModifiedText() {
    if (!currentResult) return '';
    const text = currentResult.text;
    const issues = currentResult.issues;

    // 按 position 降序排列，从后往前替换，避免位置偏移
    const sortedIssues = [...issues].map((issue, idx) => ({ ...issue, _idx: idx }))
        .sort((a, b) => b.position - a.position);

    let result = text;

    for (const issue of sortedIssues) {
        if (issueStates[issue._idx] !== 'accepted') continue;
        // 建议性说明（如"（建议…）"）没有具体替换内容，接受后不应插入原文
        if (!isRealSuggestion(issue)) continue;
        if (issue.position < 0 || issue.end_position > result.length) continue;
        // 若原文已被编辑导致该位置文本变化，则跳过，避免改错位置
        if (result.substring(issue.position, issue.end_position) !== (issue.original || '')) continue;

        result = result.substring(0, issue.position) +
                 issue.suggestion +
                 result.substring(issue.end_position);
    }

    return result;
}

// ============================================================
// 获取带修订痕迹的文本（文本输入模式导出用）
// ============================================================
function getModifiedTextWithTrackChanges() {
    if (!currentResult) return '';
    const text = currentResult.text;
    const issues = currentResult.issues;

    // 按 position 降序排列，从后往前插入标记
    const sortedIssues = [...issues].map((issue, idx) => ({ ...issue, _idx: idx }))
        .sort((a, b) => b.position - a.position);

    let result = text;

    for (const issue of sortedIssues) {
        if (issueStates[issue._idx] !== 'accepted') continue;
        // 建议性说明（如"（建议…）"）没有具体替换内容，修订痕迹中不插入原文
        if (!isRealSuggestion(issue)) continue;
        if (issue.position < 0 || issue.end_position > result.length) continue;
        // 若原文已被编辑导致该位置文本变化，则跳过，避免标记错位置
        if (result.substring(issue.position, issue.end_position) !== (issue.original || '')) continue;

        const original = result.substring(issue.position, issue.end_position);
        const suggestion = issue.suggestion || '';
        const marker = suggestion
            ? `【删除:${original}→修改为:${suggestion}】`
            : `【删除:${original}】`;

        result = result.substring(0, issue.position) +
                 marker +
                 result.substring(issue.end_position);
    }

    return result;
}
// ============================================================
function exportModifiedFile() {
    if (!currentResult) return;

    const acceptedIssues = currentResult.issues.filter((_, idx) => issueStates[idx] === 'accepted');
    const trackChanges = document.getElementById('trackChangesCheckbox')?.checked ?? false;

    // 如果是文本输入（无文件），导出为 TXT
    if (!currentResult.file_id) {
        let text;
        if (trackChanges) {
            // 修订模式：在原文上标记修改痕迹
            text = getModifiedTextWithTrackChanges();
        } else {
            text = getModifiedText();
        }
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        const ts = `${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
        a.download = `直接输入文本_修改版_${ts}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        return;
    }

    // 文件上传：在原始文件上做查找替换，保留原格式
    const replacements = acceptedIssues.map(issue => ({
        original: issue.original,
        suggestion: issue.suggestion || ''
    }));
    // 合并用户查找替换产生的替换对（直接编辑，无需逐条确认）
    for (const [original, suggestion] of Object.entries(userReplacements)) {
        if (original) replacements.push({ original: original, suggestion: suggestion || '' });
    }

    fetch('/api/export-original', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            file_id: currentResult.file_id,
            replacements: replacements,
            filename: currentResult.filename,
            track_changes: trackChanges
        })
    })
    .then(res => {
        if (!res.ok) {
            return res.json().then(err => { throw new Error(err.error || '导出失败'); });
        }
        // 从 Content-Disposition 提取文件名
        const cd = res.headers.get('Content-Disposition');
        let downloadName = '修改后文件';
        if (cd) {
            const match = cd.match(/filename\*?=(?:UTF-8'')?(.+)/);
            if (match) {
                downloadName = decodeURIComponent(match[1].replace(/['"]/g, ''));
            }
        }
        return res.blob().then(blob => ({ blob, downloadName }));
    })
    .then(({ blob, downloadName }) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = downloadName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    })
    .catch(err => showToast('导出失败: ' + err.message, 'error'));
}

// ============================================================
// 导出检查报告
// ============================================================
function exportReport() {
    if (!currentResult) return;

    fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentResult)
    })
    .then(res => res.blob())
    .then(blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = '原文检查报告.html';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    })
    .catch(err => showToast('导出失败: ' + err.message, 'error'));
}

// ============================================================
// 交互：点击问题跳转到文本位置
// ============================================================
function scrollToHighlight(issueId) {
    document.querySelectorAll('.issue-highlight').forEach(el => {
        el.classList.remove('active');
    });
    document.querySelectorAll('.issue-card').forEach(el => {
        el.classList.remove('active');
    });

    const highlight = document.querySelector(`[data-issue-id="${issueId}"]`);
    if (highlight) {
        highlight.classList.add('active');
        highlight.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    const card = document.getElementById(`card-${issueId}`);
    if (card) {
        card.classList.add('active');
    }
}

function scrollToIssue(issueId) {
    const card = document.getElementById(`card-${issueId}`);
    if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.classList.add('active');
        setTimeout(() => card.classList.remove('active'), 2000);
    }
}

// ============================================================
// 重新检查：编辑后对修改文本重新发起检查
// ============================================================

/**
 * 路由函数：根据 _pendingRecheck 状态决定行为
 * - true：对修改后的文本重新发起 AI 检查（保留编辑成果）
 * - false：返回上传页面（原始行为）
 */
function handleRecheck() {
    if (currentResult && currentResult._pendingRecheck) {
        recheckModifiedText();
    } else {
        resetPage();
    }
}

/**
 * 对 currentResult.text（编辑后的文本）重新发起检查。
 * 使用文本模式提交到 /api/analyze，检查完成后 showResult() 会自动
 * 重置状态（包括清除 _pendingRecheck 标记）。
 */
function recheckModifiedText() {
    if (!currentResult || !currentResult.text) return;

    // 如果在编辑模式，先退出
    if (editMode) cancelEdit();

    // 复用上次检查的场景
    const scenario = currentResult.scenario || selectedScenario;
    const modifiedText = currentResult.text;
    showLoading(LOADING_STEPS_TEXT, modifiedText.length);

    const formData = new FormData();
    formData.append('text', modifiedText);
    formData.append('scenario', scenario);
    formData.append('enable_security', securityEnabled ? 'true' : 'false');
    formData.append('enable_sensitive', sensitiveEnabled ? 'true' : 'false');
    formData.append('enable_ad_extreme', adExtremeEnabled ? 'true' : 'false');
    // 使用本次检查保存的术语数据（术语已在检查完成后从UI清除）
    if (_lastCheckGlossary) formData.append('custom_glossary', _lastCheckGlossary);
    if (_lastCheckBanned) formData.append('banned_words', _lastCheckBanned);

    fetch('/api/analyze', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        onLoadingDataReceived(data, !!data.error);
    })
    .catch(err => {
        onLoadingDataReceived({ error: '请求失败: ' + err.message }, true);
    });
}

// ============================================================
// 重置页面
// ============================================================
function resetPage() {
    currentResult = null;
    issueStates = {};
    previewMode = false;
    editMode = false;
    lastBatchSnapshot = null;
    _lastCheckGlossary = '';
    _lastCheckBanned = '';
    hideBatchUndoToast();
    clearSessionState();
    const _hint = document.getElementById('glossaryUsedHint');
    if (_hint) _hint.style.display = 'none';
    document.getElementById('uploadSection').style.display = 'block';
    document.getElementById('resultSection').style.display = 'none';
    const topRightResultActions = document.getElementById('topRightResultActions');
    if (topRightResultActions) topRightResultActions.style.display = 'none';
    const topRightDivider = document.getElementById('topRightDivider');
    if (topRightDivider) topRightDivider.style.display = 'none';
    window._hasResult = false;
    fileInput.value = '';
    textInput.value = '';
    textCharCount.textContent = '0 字';
    window.scrollTo(0, 0);
}

// ============================================================
// 键盘快捷键
// ============================================================
document.addEventListener('keydown', async (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        if (document.getElementById('textMode').classList.contains('active')) {
            analyzeText();
        }
    }
    if (e.key === 'Escape' && currentResult) {
        if (editMode) {
            // 编辑模式下 Esc = 退出编辑
            cancelEdit();
        } else if (currentResult._pendingRecheck) {
            // 原文已修改：Esc 提示是否重新检查
            if (await confirmDialog('确定要重新检查修改后的原文吗？')) {
                recheckModifiedText();
            }
        } else {
            // 正常审阅中：Esc 提示是否返回上传页面
            if (await confirmDialog('确定要返回上传页面吗？')) {
                resetPage();
            }
        }
    }
});

// ============================================================
// 页面加载时恢复上次审阅进度 + 加载自定义术语表/禁用词库
// ============================================================
tryRestoreSession();
loadGlossary();
renderGlossaryTerms();
renderBannedWords();
renderSettingsSummary();

// ============================================================
// 隐私政策弹窗
// ============================================================
function openPrivacyPolicy() {
    var modal = document.getElementById('privacyModal');
    if (modal) {
        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }
}

function closePrivacyPolicy() {
    var modal = document.getElementById('privacyModal');
    if (modal) {
        modal.classList.remove('show');
        document.body.style.overflow = '';
    }
}

// 隐私政策弹窗内 Esc 关闭
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.getElementById('privacyModal') && document.getElementById('privacyModal').classList.contains('show')) {
        closePrivacyPolicy();
    }
});

// 检查前确认弹窗：点击遮罩或 Esc 取消（不检查、不去设置，留在上传页）
document.getElementById('settingsConfirmOverlay').addEventListener('click', function(e) {
    if (e.target === this) closeSettingsConfirm(false);
});
document.addEventListener('keydown', function(e) {
    const ov = document.getElementById('settingsConfirmOverlay');
    if (e.key === 'Escape' && ov && ov.style.display === 'flex') {
        closeSettingsConfirm(false);
    }
});

// ============================================================
// 顶部工作区：当前只有「文字智能检查」单一模式
// ============================================================

function switchMainMode(mode) {
    const uploadSection = document.getElementById('uploadSection');
    const resultSection = document.getElementById('resultSection');
    const topRightResultActions = document.getElementById('topRightResultActions');

    if (uploadSection) uploadSection.style.display = '';
    if (topRightResultActions) topRightResultActions.style.display = 'none';
    const topRightDivider = document.getElementById('topRightDivider');
    if (topRightDivider) topRightDivider.style.display = 'none';
    // 若有检查结果，恢复结果视图（工具栏在 enterResultView 中再行显示）
    if (window._hasResult && resultSection) {
        resultSection.style.display = '';
    }
}

// 切换右侧资源栏标签（检查设置 / 术语库 / 禁用词 / 筛选器）
function switchSidebarTab(tab) {
    document.querySelectorAll('.sidebar-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tab);
    });
    const cap = tab.charAt(0).toUpperCase() + tab.slice(1);
    const target = document.getElementById('sidebar' + cap);
    document.querySelectorAll('.sidebar-tab-content').forEach(c => {
        c.classList.toggle('active', c === target);
    });
}

// 进入结果视图：隐藏上传区、显示结果区，并显示全局结果操作（文件修改操作在编辑器上方，随结果区显隐）
function enterResultView() {
    const uploadSection = document.getElementById('uploadSection');
    const resultSection = document.getElementById('resultSection');
    const topRightResultActions = document.getElementById('topRightResultActions');
    if (uploadSection) uploadSection.style.display = 'none';
    if (resultSection) resultSection.style.display = 'block';
    if (topRightResultActions) topRightResultActions.style.display = 'flex';
    const topRightDivider = document.getElementById('topRightDivider');
    if (topRightDivider) topRightDivider.style.display = '';
}

// 工具栏「开始检查」：按当前输入方式触发上传 / 文本检查，
// 若此前用户点了「去设置」仍保留着待上传内容，则直接继续
function triggerStart() {
    // 若仍有挂起的上传（确认弹窗尚未关闭时点了「开始检查」），直接继续该上传
    if (_deferredUpload) {
        doUploadDeferred();
        return;
    }
    if (currentInputMode === 'text') {
        const text = document.getElementById('textInput');
        if (!text || !text.value.trim()) {
            showToast('请先粘贴需要检查的文本', 'warning');
            return;
        }
        analyzeText();
        return;
    }
    const fileInput = document.getElementById('fileInput');
    if (fileInput && fileInput.files && fileInput.files.length > 0) {
        handleFile(fileInput.files[0]);
    } else {
        showToast('请先选择要检查的文件', 'warning');
    }
}


// 页面加载完成：渲染上传区底部的六层检查模块
renderLayerModules();

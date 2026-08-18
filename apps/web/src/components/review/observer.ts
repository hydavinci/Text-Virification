import type { InjectionKey } from 'vue'

export interface ReviewIntersectionObserverEntry {
  isIntersecting: boolean
}

export type ReviewIntersectionObserverCallback = (
  entries: readonly ReviewIntersectionObserverEntry[]
) => void

export interface ReviewIntersectionObserver {
  observe(element: Element): void
  disconnect(): void
}

export type ReviewIntersectionObserverFactory = (
  callback: ReviewIntersectionObserverCallback
) => ReviewIntersectionObserver

export const reviewIntersectionObserverFactoryKey: InjectionKey<ReviewIntersectionObserverFactory> =
  Symbol('reviewIntersectionObserverFactory')

export const browserReviewIntersectionObserverFactory: ReviewIntersectionObserverFactory = (
  callback
) => {
  if (typeof IntersectionObserver === 'undefined') {
    return {
      observe() {},
      disconnect() {}
    }
  }

  const observer = new IntersectionObserver((entries) => callback(entries))

  return {
    observe(element) {
      observer.observe(element)
    },
    disconnect() {
      observer.disconnect()
    }
  }
}

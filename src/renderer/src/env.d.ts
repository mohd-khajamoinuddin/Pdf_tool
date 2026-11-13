import type { SuiteApi } from '../../shared/api'

declare global {
  interface Window {
    suite: SuiteApi
  }
}

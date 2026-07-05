import axios from 'axios'

export interface ApiError {
  status: number
  message: string
  traceId?: string
  detail?: string
}

declare module 'axios' {
  interface AxiosError {
    apiError?: ApiError
  }
}

export const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const skipRedirect = error?.config?.headers?.['X-Skip-Auth-Redirect'] === 'true'

    if (
      !skipRedirect &&
      error?.response?.status === 401 &&
      typeof window !== 'undefined' &&
      !window.location.pathname.startsWith('/login')
    ) {
      const next = `${window.location.pathname}${window.location.search}`
      const detail =
        typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : ''
      const reason = detail ? `&reason=${encodeURIComponent(detail)}` : ''
      window.location.assign(`/login?next=${encodeURIComponent(next)}${reason}`)
    }

    const apiError: ApiError = {
      status: error?.response?.status ?? 0,
      message: error?.message ?? 'Unknown error',
      traceId: error?.response?.data?.trace_id,
      detail: typeof error?.response?.data?.detail === 'string'
        ? error.response.data.detail
        : undefined,
    }
    if (error) {
      error.apiError = apiError
    }

    return Promise.reject(error)
  }
)

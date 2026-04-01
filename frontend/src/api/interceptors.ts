/**
 * API 拦截器
 *
 * 功能:
 * 1. 自动传递 Trace ID 到后端
 * 2. 响应中提取 Trace ID
 * 3. 错误时保存 Trace ID 供调试使用
 */

import axios, { AxiosError, AxiosResponse } from 'axios'

// 最后一次成功的 Trace ID
let lastTraceId = ''

// 创建 axios 实例
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 如果有上次的 Trace ID，传递下去（支持链路追踪）
    if (lastTraceId) {
      config.headers['X-Trace-ID'] = lastTraceId
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response: AxiosResponse) => {
    // 从响应头提取 Trace ID
    const traceId = response.headers['x-trace-id']
    if (traceId) {
      lastTraceId = traceId
      // 暴露到全局，便于调试
      window.__lastTraceId = traceId
    }
    return response
  },
  async (error: AxiosError) => {
    // 从错误响应中提取 Trace ID
    const traceId =
      error.response?.headers?.['x-trace-id'] ||
      (error.response?.data as any)?.trace_id ||
      lastTraceId ||
      'unknown'

    // 保存到全局
    window.__lastTraceId = traceId
    window.__lastError = {
      message: (error.response?.data as any)?.error || error.message,
      traceId,
      timestamp: new Date().toISOString(),
      status: error.response?.status,
    }

    return Promise.reject({
      ...error,
      traceId,
      trace_id: traceId,  // 兼容两种写法
    })
  }
)

// 导出 api 实例
export { api }

export function getLastTraceId(): string {
  return lastTraceId
}

export function getLastError(): {
  message: string
  traceId: string
  timestamp: string
  status?: number
} | null {
  return (window as any).__lastError || null
}

// 类型声明（可选，用于 IDE 提示）
declare global {
  interface Window {
    __lastTraceId?: string
    __lastError?: {
      message: string
      traceId: string
      timestamp: string
      status?: number
    }
  }
}

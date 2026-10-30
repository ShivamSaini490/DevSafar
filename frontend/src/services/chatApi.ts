import type { TemporaryChatRequest, TemporaryChatResponse } from '../types/chat.ts'
import { apiRequest } from './apiClient.ts'

export const chatApi = {
  sendTemporaryMessage: (payload: TemporaryChatRequest) =>
    apiRequest<TemporaryChatResponse>('/api/v1/chat/temporary', { method: 'POST', body: payload }),
}

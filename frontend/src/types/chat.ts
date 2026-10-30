export type TripStatus = 'needs_clarification' | 'completed' | 'failed'

/** Only the trip fields the landing page reads. The full contract lives in backend/app/schemas/trip.py. */
export interface TripSummary {
  trip_id: string
  status: TripStatus
  feasible: boolean | null
  warnings: string[]
}

export interface TemporaryChatRequest {
  temp_session_id: string
  temp_token: string | null
  content: string
}

export interface TemporaryChatResponse {
  assistant_message: string
  temp_token: string | null
  context_message_count: number
  expires_in_seconds: number
  trip: TripSummary
}

export interface PlannerMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  trip?: TripSummary
}

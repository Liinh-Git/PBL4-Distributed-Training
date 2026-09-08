import { useState, useEffect, useCallback, useRef } from 'react'
import { attemptsApi } from '../api/attempts'
import { createAttemptRealtimeClient } from '../live/realtimeClient'
import type { WsStatus, RealtimeMessage, AttemptRealtimeClient } from '../live/realtimeClient'
import type { AttemptDetail, AttemptSnapshot, WorkerSessionItem, StepListItem, EventListItem } from '../domain/types'

interface UseRealtimeAttemptResult {
  attempt: AttemptDetail | null
  snapshot: AttemptSnapshot | null
  workers: WorkerSessionItem[]
  steps: StepListItem[]
  events: EventListItem[]
  wsStatus: WsStatus
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useRealtimeAttempt(attemptId: string | null): UseRealtimeAttemptResult {
  const [attempt, setAttempt] = useState<AttemptDetail | null>(null)
  const [snapshot, setSnapshot] = useState<AttemptSnapshot | null>(null)
  const [workers, setWorkers] = useState<WorkerSessionItem[]>([])
  const [steps, setSteps] = useState<StepListItem[]>([])
  const [events, setEvents] = useState<EventListItem[]>([])
  const [wsStatus, setWsStatus] = useState<WsStatus>('disconnected')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clientRef = useRef<AttemptRealtimeClient | null>(null)

  const fetchInitial = useCallback(async () => {
    if (!attemptId) return
    setLoading(true)
    setError(null)
    try {
      const [attemptRes, snapshotRes, workersRes, stepsRes, eventsRes] = await Promise.allSettled([
        attemptsApi.get(attemptId),
        attemptsApi.snapshot(attemptId),
        attemptsApi.workers(attemptId),
        attemptsApi.steps(attemptId, { limit: 100 }),
        attemptsApi.events(attemptId, { limit: 200 }),
      ])
      if (attemptRes.status === 'fulfilled') setAttempt(attemptRes.value)
      if (snapshotRes.status === 'fulfilled') setSnapshot(snapshotRes.value)
      if (workersRes.status === 'fulfilled') setWorkers(workersRes.value.data)
      if (stepsRes.status === 'fulfilled') setSteps(stepsRes.value.data)
      if (eventsRes.status === 'fulfilled') setEvents(eventsRes.value.data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [attemptId])

  useEffect(() => {
    if (!attemptId) return
    fetchInitial()

    const client = createAttemptRealtimeClient(attemptId)
    clientRef.current = client

    const offStatus = client.onStatus(setWsStatus)
    const offMessage = client.onMessage((msg: RealtimeMessage) => {
      if (msg.type === 'SNAPSHOT') {
        const payload = msg.data as { snapshot?: AttemptSnapshot }
        if (payload?.snapshot) {
          setSnapshot(payload.snapshot)
        }
      }
      if (msg.type === 'GAP') {
        fetchInitial()
      }
      if (msg.type === 'RUNTIME_EVENT' || msg.type === 'MANAGEMENT_EVENT') {
        const ev = msg.data as EventListItem
        setEvents((prev) => {
          const exists = prev.some(
            (e) =>
              (e.event_id && ev.event_id && e.event_id === ev.event_id) ||
              (e.runtime_event_seq !== undefined &&
                ev.runtime_event_seq !== undefined &&
                e.runtime_event_seq === ev.runtime_event_seq)
          )
          if (exists) return prev
          return [ev, ...prev].slice(0, 500)
        })
      }
      if (msg.type === 'ATTEMPT_STATE_CHANGE') {
        const data = msg.data as Partial<AttemptDetail>
        setAttempt((prev) => (prev ? { ...prev, ...data } : prev))
      }
      if (msg.type === 'WORKER_STATE_CHANGE') {
        attemptsApi.workers(attemptId).then((r) => setWorkers(r.data)).catch(() => {})
      }
      if (msg.type === 'STEP_COMMITTED') {
        const step = msg.data as StepListItem
        setSteps((prev) => [...prev, step])
      }
    })

    client.connect()

    return () => {
      offStatus()
      offMessage()
      client.disconnect()
      clientRef.current = null
    }
  }, [attemptId, fetchInitial])

  return { attempt, snapshot, workers, steps, events, wsStatus, loading, error, refresh: fetchInitial }
}

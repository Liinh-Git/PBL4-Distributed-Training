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
  hasGap: boolean
  isStale: boolean
  appliedSeq: number | null
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
  const [hasGap, setHasGap] = useState(false)

  const clientRef = useRef<AttemptRealtimeClient | null>(null)
  const appliedSeqRef = useRef<number | null>(null)
  const pendingBufferRef = useRef<Map<number, RealtimeMessage>>(new Map())

  const applySingleEvent = useCallback((msg: RealtimeMessage) => {
    const rawPayload = (msg.payload || {}) as Record<string, unknown>
    const seq = msg.runtime_event_seq
    const ev: EventListItem = {
      event_id: (rawPayload?.event_id as string) || (msg.attempt_id && seq !== null ? `${msg.attempt_id}-${seq}` : undefined),
      attempt_id: msg.attempt_id || (rawPayload?.attempt_id as string) || undefined,
      runtime_event_seq: seq ?? undefined,
      event_type: (rawPayload?.event_type as string) || 'UNKNOWN',
      severity: (rawPayload?.severity as any) || 'INFO',
      source_component: (rawPayload?.source_component as string) || 'Runtime',
      payload: rawPayload,
      occurred_at: msg.occurred_at || (rawPayload?.occurred_at as string) || new Date().toISOString(),
    }

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

    if (rawPayload?.event_type === 'ATTEMPT_STATE_CHANGED' || rawPayload?.event_type === 'ATTEMPT_STATE_CHANGE') {
      const newState = (rawPayload?.to_state || rawPayload?.state) as any
      if (newState) {
        setAttempt((prev) => (prev ? { ...prev, state: newState } : prev))
      }
    }
    if (rawPayload?.event_type === 'STEP_COMMITTED') {
      const step = rawPayload as unknown as StepListItem
      setSteps((prev) => [...prev, step])
    }
  }, [])

  const drainContiguousBufferedEvents = useCallback(() => {
    if (appliedSeqRef.current === null) return
    let nextSeq = appliedSeqRef.current + 1
    while (pendingBufferRef.current.has(nextSeq)) {
      const nextMsg = pendingBufferRef.current.get(nextSeq)!
      pendingBufferRef.current.delete(nextSeq)
      appliedSeqRef.current = nextSeq
      applySingleEvent(nextMsg)
      clientRef.current?.setHighestContiguousSeq(nextSeq)
      nextSeq++
    }
    if (pendingBufferRef.current.size === 0) {
      setHasGap(false)
    }
  }, [applySingleEvent])

  const fetchInitial = useCallback(async () => {
    if (!attemptId) return
    setLoading(true)
    setError(null)
    setHasGap(false)
    try {
      appliedSeqRef.current = null
      pendingBufferRef.current.clear()
      setEvents([])
      const [attemptRes, snapshotRes, workersRes, stepsRes] = await Promise.allSettled([
        attemptsApi.get(attemptId),
        attemptsApi.snapshot(attemptId),
        attemptsApi.workers(attemptId),
        attemptsApi.steps(attemptId, { limit: 100 }),
      ])
      if (attemptRes.status === 'fulfilled') setAttempt(attemptRes.value)
      if (snapshotRes.status === 'fulfilled') {
        setSnapshot(snapshotRes.value)
        if (snapshotRes.value?.runtime_event_seq != null) {
          appliedSeqRef.current = snapshotRes.value.runtime_event_seq
          clientRef.current?.setHighestContiguousSeq(snapshotRes.value.runtime_event_seq)
        }
      }
      if (workersRes.status === 'fulfilled') setWorkers(workersRes.value.data)
      if (stepsRes.status === 'fulfilled') setSteps(stepsRes.value.data)

      let afterSeq = appliedSeqRef.current ?? 0
      while (true) {
        const eventPage = await attemptsApi.events(attemptId, { limit: 200, after_seq: afterSeq })
        if (eventPage.meta.gap_detected) {
          setHasGap(true)
          break
        }
        if (eventPage.data.length === 0) break
        let expectedSeq = afterSeq + 1
        let contiguous = true
        for (const event of eventPage.data) {
          if (event.runtime_event_seq !== expectedSeq) {
            contiguous = false
            break
          }
          applySingleEvent({
            kind: 'EVENT',
            attempt_id: attemptId,
            runtime_event_seq: event.runtime_event_seq,
            occurred_at: event.occurred_at,
            payload: {
              event_type: event.event_type,
              severity: event.severity,
              source_component: event.source_component,
              ...(event.details || event.payload || {}),
            },
          })
          appliedSeqRef.current = expectedSeq
          expectedSeq += 1
        }
        if (!contiguous) {
          setHasGap(true)
          break
        }
        afterSeq = expectedSeq - 1
        clientRef.current?.setHighestContiguousSeq(afterSeq)
        if (eventPage.meta.complete) break
      }
      appliedSeqRef.current = afterSeq
      drainContiguousBufferedEvents()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [attemptId, applySingleEvent, drainContiguousBufferedEvents])

  useEffect(() => {
    if (!attemptId) return
    fetchInitial()

    const client = createAttemptRealtimeClient(attemptId)
    clientRef.current = client

    const offStatus = client.onStatus(setWsStatus)
    const offMessage = client.onMessage((msg: RealtimeMessage) => {
      const kind = (msg.kind || '').toUpperCase()

      if (kind === 'SNAPSHOT') {
        const rawPayload = (msg.payload || {}) as Record<string, unknown>
        const snap = (rawPayload.snapshot || rawPayload) as AttemptSnapshot
        const snapSeq = msg.runtime_event_seq ?? (rawPayload.snapshot_seq as number | undefined)

        // Atomically replace live projection
        setSnapshot(snap)
        if (snap.attempt_id) {
          setAttempt((prev) => (prev ? { ...prev, state: (snap.state as any) || prev.state } : prev))
        }
        if (snap.workers && Array.isArray(snap.workers)) {
          setWorkers(snap.workers as unknown as WorkerSessionItem[])
        }

        if (snapSeq !== null && snapSeq !== undefined) {
          appliedSeqRef.current = snapSeq
          client.setHighestContiguousSeq(snapSeq)
          setHasGap(false)

          // Discard obsolete buffered entries <= snapSeq
          for (const [bufferedSeq] of pendingBufferRef.current.entries()) {
            if (bufferedSeq <= snapSeq) {
              pendingBufferRef.current.delete(bufferedSeq)
            }
          }

          drainContiguousBufferedEvents()
        }
      } else if (kind === 'GAP') {
        // GAP preserves stale/incomplete-history UX
        setHasGap(true)
      } else if (kind === 'EVENT') {
        const seq = msg.runtime_event_seq
        if (seq === null || seq === undefined) {
          // Non-sequenced event: apply immediately
          applySingleEvent(msg)
          return
        }

        const currentApplied = appliedSeqRef.current
        if (currentApplied === null) {
          pendingBufferRef.current.set(seq, msg)
          setHasGap(true)
          return
        }

        if (seq <= currentApplied) {
          // Duplicate or already-applied event: ignore
          return
        }

        if (seq > currentApplied + 1) {
          // Gap: BUFFER IT. DO NOT update UI state. DO NOT append to live history.
          pendingBufferRef.current.set(seq, msg)
          setHasGap(true)
          return
        }

        // seq === currentApplied + 1: apply and drain contiguous buffered events
        appliedSeqRef.current = seq
        applySingleEvent(msg)
        client.setHighestContiguousSeq(seq)
        drainContiguousBufferedEvents()
      }
    })

    client.connect()

    return () => {
      offStatus()
      offMessage()
      client.disconnect()
      clientRef.current = null
      pendingBufferRef.current.clear()
    }
  }, [attemptId, fetchInitial, applySingleEvent, drainContiguousBufferedEvents])

  const isStale = wsStatus !== 'connected' || hasGap || Boolean(snapshot?.stale)

  return {
    attempt,
    snapshot,
    workers,
    steps,
    events,
    wsStatus,
    loading,
    error,
    hasGap,
    isStale,
    appliedSeq: appliedSeqRef.current,
    refresh: fetchInitial,
  }
}

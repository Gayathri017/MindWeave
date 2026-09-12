import { useCallback, useRef, useState } from 'react'

/**
 * Wraps the browser's MediaRecorder API into a simple start/stop hook.
 * Kept separate from any one component -- the actual recording logic has
 * nothing to do with rendering, and this makes it independently testable
 * (and reusable) if voice capture ever shows up somewhere else in the app.
 */
export function useAudioRecorder({ onComplete, onError }) {
  const [isRecording, setIsRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)

  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const streamRef = useRef(null)
  const timerRef = useRef(null)

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []

      const recorder = new MediaRecorder(stream)
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        streamRef.current?.getTracks().forEach((track) => track.stop())
        onComplete?.(blob)
      }

      mediaRecorderRef.current = recorder
      recorder.start()
      setIsRecording(true)
      setSeconds(0)
      timerRef.current = setInterval(() => setSeconds((current) => current + 1), 1000)
    } catch {
      onError?.('Could not access your microphone. Check your browser permissions and try again.')
    }
  }, [onComplete, onError])

  const stop = useCallback(() => {
    mediaRecorderRef.current?.stop()
    clearInterval(timerRef.current)
    setIsRecording(false)
  }, [])

  return { isRecording, seconds, start, stop }
}
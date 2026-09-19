import { useEffect, useRef, useState } from 'react'

const NO_AUDIO_SCENE_MS = 5000

function PlayIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  )
}

function PauseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="5" width="4" height="14" />
      <rect x="14" y="5" width="4" height="14" />
    </svg>
  )
}

export default function ExplainerPlayer({ explainer, onClose }) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const audioRef = useRef(null)
  const fallbackTimerRef = useRef(null)

  const scene = explainer.scenes[index]
  const isLast = index === explainer.scenes.length - 1

  function goToNext() {
    setIndex((current) => (current < explainer.scenes.length - 1 ? current + 1 : current))
    if (isLast) setPlaying(false)
  }

  useEffect(() => {
    clearTimeout(fallbackTimerRef.current)

    if (!playing) return

    if (scene.audio) {
      audioRef.current?.play().catch(() => {})
    } else {
      // No narration audio for this scene (generation failed) -- still
      // advance automatically after a fixed pause, so the player never
      // just silently stalls on one scene.
      fallbackTimerRef.current = setTimeout(goToNext, NO_AUDIO_SCENE_MS)
    }

    return () => clearTimeout(fallbackTimerRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, playing])

  function togglePlaying() {
    if (playing) {
      audioRef.current?.pause()
      clearTimeout(fallbackTimerRef.current)
      setPlaying(false)
    } else {
      setPlaying(true)
    }
  }

  function goToPrev() {
    setIndex((current) => (current > 0 ? current - 1 : current))
  }

  return (
    <div className="explainer-overlay" onMouseDown={onClose}>
      <div className="explainer-player" onMouseDown={(event) => event.stopPropagation()}>
        <div className="explainer-header">
          <span className="explainer-title">{explainer.title}</span>
          <button type="button" className="delete-button" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        <div className="explainer-stage">
          {scene.image ? (
            <img className="explainer-image" src={scene.image} alt="" />
          ) : (
            <div className="explainer-image-placeholder" />
          )}
        </div>

        <p className="explainer-caption">{scene.narration}</p>

        {scene.audio && (
          <audio ref={audioRef} src={scene.audio} onEnded={goToNext} style={{ display: 'none' }} />
        )}

        <div className="explainer-controls">
          <button type="button" className="explainer-nav-button" onClick={goToPrev} disabled={index === 0}>
            &lsaquo;
          </button>
          <button type="button" className="explainer-play-button" onClick={togglePlaying}>
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
          <button type="button" className="explainer-nav-button" onClick={goToNext} disabled={isLast}>
            &rsaquo;
          </button>
          <span className="explainer-progress">
            {index + 1} / {explainer.scenes.length}
          </span>
        </div>
      </div>
    </div>
  )
}

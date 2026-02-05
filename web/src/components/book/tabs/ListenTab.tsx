import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { BookData } from './useBookData'
import { useChapters } from './useBookData'

interface ListenTabProps {
  bookId: string
  book: BookData
}

interface Chapter {
  _docID: string
  title?: string
  level?: number
  level_name?: string
  entry_number?: string
  matter_type?: string
  audio_include?: boolean
  sort_order: number
  polished_text?: string
  polish_complete?: boolean
}

interface ChapterAudio {
  chapter_idx: number
  title?: string
  duration_ms?: number
  segment_count?: number
  cost_usd?: number
  audio_file?: string
  download_url?: string
}

interface AudioStatus {
  book_id: string
  status: string
  error_message?: string
  provider?: string
  voice?: string
  format?: string
  total_duration_ms?: number
  total_cost_usd?: number
  chapter_count?: number
  segment_count?: number
  chapters?: ChapterAudio[]
}

interface GenerateResponse {
  job_id: string
  book_id: string
  status: string
  chapters: number
  provider: string
}

interface TTSVoice {
  voice_id: string
  name: string
  description?: string
}

interface TTSConfig {
  provider: string
  model: string
  default_voice?: string
  default_format: string
  voices: TTSVoice[]
  formats: string[]
  voice_cloning_url?: string
}

export function ListenTab({ bookId, book }: ListenTabProps) {
  const queryClient = useQueryClient()
  const audioRef = useRef<HTMLAudioElement>(null)
  const textContainerRef = useRef<HTMLDivElement>(null)
  const [currentChapter, setCurrentChapter] = useState<number | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [selectedVoice, setSelectedVoice] = useState<string>('')

  // Fetch chapters with polished text
  const { data: chaptersData } = useChapters(bookId)
  const chapterTextData = (chaptersData?.chapters || []) as Chapter[]

  // Scroll text to top when chapter changes
  useEffect(() => {
    if (textContainerRef.current) {
      textContainerRef.current.scrollTop = 0
    }
  }, [currentChapter])

  // Fetch TTS config (voices, formats, etc.)
  const { data: ttsConfig } = useQuery<TTSConfig>({
    queryKey: ['tts-config'],
    queryFn: async () => {
      const res = await fetch('/api/tts/config')
      if (!res.ok) throw new Error('Failed to fetch TTS config')
      return res.json()
    },
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  })

  // Fetch audio status
  const { data: audioStatus, isLoading, refetch } = useQuery<AudioStatus>({
    queryKey: ['audio-status', bookId],
    queryFn: async () => {
      const res = await fetch(`/api/books/${bookId}/audio`)
      if (!res.ok) throw new Error('Failed to fetch audio status')
      return res.json()
    },
    refetchInterval: (query) => {
      // Poll every 5s while generating
      const data = query.state.data
      if (data?.status === 'generating') return 5000
      return false
    },
  })

  // Generate audio mutation
  const generateMutation = useMutation({
    mutationFn: async () => {
      const body: { voice?: string } = {}
      if (selectedVoice) {
        body.voice = selectedVoice
      }
      const res = await fetch(`/api/books/${bookId}/generate/audio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        let message = 'Failed to start audio generation'
        try {
          const error = await res.json()
          message = error.error || message
        } catch {
          // Ignore JSON parse errors and use fallback message.
        }
        throw new Error(message)
      }
      return res.json() as Promise<GenerateResponse>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['audio-status', bookId] })
    },
  })

  // Audio event handlers
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const handleTimeUpdate = () => setCurrentTime(audio.currentTime)
    const handleDurationChange = () => setDuration(audio.duration)
    const handleEnded = () => {
      setIsPlaying(false)
      // Auto-play next chapter
      if (audioStatus?.chapters && currentChapter !== null) {
        const nextIdx = currentChapter + 1
        const nextChapter = audioStatus.chapters.find(c => c.chapter_idx === nextIdx)
        if (nextChapter?.download_url) {
          setCurrentChapter(nextIdx)
        }
      }
    }
    const handlePlay = () => setIsPlaying(true)
    const handlePause = () => setIsPlaying(false)

    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('durationchange', handleDurationChange)
    audio.addEventListener('ended', handleEnded)
    audio.addEventListener('play', handlePlay)
    audio.addEventListener('pause', handlePause)

    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('durationchange', handleDurationChange)
      audio.removeEventListener('ended', handleEnded)
      audio.removeEventListener('play', handlePlay)
      audio.removeEventListener('pause', handlePause)
    }
  }, [audioStatus?.chapters, currentChapter])

  // Load chapter audio when changed
  useEffect(() => {
    if (currentChapter === null || !audioStatus?.chapters) return
    const chapter = audioStatus.chapters.find(c => c.chapter_idx === currentChapter)
    if (chapter?.download_url && audioRef.current) {
      audioRef.current.src = chapter.download_url
      audioRef.current.load()
      audioRef.current.play().catch(() => {})
    }
  }, [currentChapter, audioStatus?.chapters])

  const formatTime = (seconds: number) => {
    if (!isFinite(seconds)) return '0:00'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const formatDuration = (ms?: number) => {
    if (!ms) return '--:--'
    const totalSeconds = Math.floor(ms / 1000)
    const hours = Math.floor(totalSeconds / 3600)
    const mins = Math.floor((totalSeconds % 3600) / 60)
    const secs = totalSeconds % 60
    if (hours > 0) {
      return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value)
    if (audioRef.current) {
      audioRef.current.currentTime = time
      setCurrentTime(time)
    }
  }

  const togglePlayPause = () => {
    if (!audioRef.current) return
    if (isPlaying) {
      audioRef.current.pause()
    } else {
      audioRef.current.play().catch(() => {})
    }
  }

  const playChapter = (chapterIdx: number) => {
    setCurrentChapter(chapterIdx)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  // Not started state
  if (!audioStatus || audioStatus.status === 'not_started') {
    const hasVoices = ttsConfig?.voices && ttsConfig.voices.length > 0

    return (
      <div className="bg-white rounded-lg shadow-sm border p-8 text-center">
        <div className="text-6xl mb-4">🎧</div>
        <h3 className="text-xl font-semibold text-gray-900 mb-2">Generate Audiobook</h3>
        <p className="text-gray-600 mb-6 max-w-md mx-auto">
          Convert this book to audio using AI text-to-speech. Each chapter will be generated
          as a separate audio file that you can listen to or download.
        </p>
        {book.status !== 'complete' ? (
          <div className="text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 inline-block">
            Book processing must complete before generating audio
          </div>
        ) : (
          <div className="space-y-4">
            {/* Voice selection */}
            {hasVoices && (
              <div className="max-w-xs mx-auto">
                <label htmlFor="voice-select" className="block text-sm font-medium text-gray-700 mb-1">
                  Voice
                </label>
                <select
                  id="voice-select"
                  value={selectedVoice}
                  onChange={(e) => setSelectedVoice(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="">Default voice</option>
                  {ttsConfig.voices.map((voice) => (
                    <option key={voice.voice_id} value={voice.voice_id}>
                      {voice.name}{voice.description ? ` - ${voice.description}` : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* No voices - show link to create */}
            {!hasVoices && ttsConfig?.voice_cloning_url && (
              <div className="text-sm text-gray-500 mb-2">
                <a
                  href={ttsConfig.voice_cloning_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-800 underline"
                >
                  Create a custom voice
                </a>
                {' '}to personalize your audiobook
              </div>
            )}

            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="inline-flex items-center px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {generateMutation.isPending ? (
                <>
                  <span className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full mr-2" />
                  Starting...
                </>
              ) : (
                <>
                  <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Generate Audiobook
                </>
              )}
            </button>

            {/* Show provider info */}
            {ttsConfig && (
              <div className="text-xs text-gray-400 mt-2">
                Using {ttsConfig.provider} ({ttsConfig.model})
              </div>
            )}
          </div>
        )}
        {generateMutation.error && (
          <div className="mt-4 text-red-600 text-sm">
            {generateMutation.error.message}
          </div>
        )}
      </div>
    )
  }

  if (audioStatus.status === 'failed') {
    return (
      <div className="bg-white rounded-lg shadow-sm border p-8 text-center">
        <div className="text-5xl mb-4">⚠️</div>
        <h3 className="text-xl font-semibold text-gray-900 mb-2">Audio Generation Failed</h3>
        <p className="text-gray-600 mb-4 max-w-2xl mx-auto">
          {audioStatus.error_message || 'An unexpected error occurred while generating audio.'}
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending || book.status !== 'complete'}
            className="inline-flex items-center px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {generateMutation.isPending ? 'Retrying...' : 'Retry Generation'}
          </button>
          <button
            onClick={() => refetch()}
            className="inline-flex items-center px-5 py-2.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Refresh Status
          </button>
        </div>
        {generateMutation.error && (
          <div className="mt-4 text-red-600 text-sm">
            {generateMutation.error.message}
          </div>
        )}
      </div>
    )
  }

  // Generating state
  if (audioStatus.status === 'generating') {
    const progress = audioStatus.segment_count && audioStatus.chapter_count
      ? Math.round((audioStatus.chapters?.length || 0) / audioStatus.chapter_count * 100)
      : 0

    return (
      <div className="bg-white rounded-lg shadow-sm border p-8">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-full mb-4">
            <div className="animate-pulse">
              <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
          </div>
          <h3 className="text-xl font-semibold text-gray-900">Generating Audiobook...</h3>
          <p className="text-gray-600 mt-1">This may take a while depending on the book length</p>
        </div>

        {/* Progress bar */}
        <div className="max-w-md mx-auto mb-6">
          <div className="flex justify-between text-sm text-gray-600 mb-2">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-600 rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 max-w-md mx-auto text-center">
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="text-2xl font-semibold text-gray-900">{audioStatus.chapters?.length || 0}</div>
            <div className="text-xs text-gray-500">Chapters Done</div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="text-2xl font-semibold text-gray-900">{formatDuration(audioStatus.total_duration_ms)}</div>
            <div className="text-xs text-gray-500">Duration</div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="text-2xl font-semibold text-gray-900">${(audioStatus.total_cost_usd || 0).toFixed(2)}</div>
            <div className="text-xs text-gray-500">Cost</div>
          </div>
        </div>

        <div className="text-center mt-6">
          <button
            onClick={() => refetch()}
            className="text-blue-600 hover:text-blue-800 text-sm"
          >
            Refresh Status
          </button>
        </div>
      </div>
    )
  }

  // Complete state - Audio player with integrated reader
  const audioChapters = audioStatus?.chapters || []
  const currentChapterAudio = audioChapters.find(c => c.chapter_idx === currentChapter)

  // Match chapter_idx to the same filtered/sorted chapter list used by backend TTS generation.
  const sortedAudioEligibleChapters = [...chapterTextData]
    .filter((chapter) => {
      if (!chapter.polish_complete || !chapter.polished_text) {
        return false
      }
      if (typeof chapter.audio_include === 'boolean') {
        return chapter.audio_include
      }
      return chapter.matter_type !== 'back_matter'
    })
    .sort((a, b) => a.sort_order - b.sort_order)
  const currentChapterText = currentChapter !== null ? sortedAudioEligibleChapters[currentChapter] : null

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      {/* Hidden audio element */}
      <audio ref={audioRef} />

      {/* Left side: Player + Chapter List */}
      <div className="lg:w-80 flex-shrink-0 space-y-4">
        {/* Compact Player */}
        <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
          <div className="bg-gradient-to-r from-blue-600 to-indigo-600 p-4 text-white">
            <div className="text-xs opacity-75 mb-1">Now Playing</div>
            <div className="font-semibold truncate">
              {currentChapterAudio?.title || (currentChapter !== null ? `Chapter ${currentChapter + 1}` : 'Select a chapter')}
            </div>

            {/* Progress bar */}
            <div className="mt-3">
              <input
                type="range"
                min={0}
                max={duration || 100}
                value={currentTime}
                onChange={handleSeek}
                disabled={currentChapter === null}
                className="w-full h-1.5 bg-white/30 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow-lg"
              />
              <div className="flex justify-between text-xs mt-1 opacity-75">
                <span>{formatTime(currentTime)}</span>
                <span>{formatTime(duration)}</span>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center justify-center space-x-4 mt-3">
              <button
                onClick={() => {
                  if (currentChapter !== null && currentChapter > 0) {
                    const prevChapter = audioChapters.find(c => c.chapter_idx === currentChapter - 1)
                    if (prevChapter) playChapter(currentChapter - 1)
                  }
                }}
                disabled={currentChapter === null || currentChapter === 0}
                className="p-1.5 hover:bg-white/10 rounded-full disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" />
                </svg>
              </button>

              <button
                onClick={togglePlayPause}
                disabled={currentChapter === null}
                className="p-3 bg-white text-blue-600 rounded-full hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isPlaying ? (
                  <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                  </svg>
                ) : (
                  <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                )}
              </button>

              <button
                onClick={() => {
                  if (currentChapter !== null) {
                    const nextChapter = audioChapters.find(c => c.chapter_idx === currentChapter + 1)
                    if (nextChapter) playChapter(currentChapter + 1)
                  }
                }}
                disabled={currentChapter === null || !audioChapters.find(c => c.chapter_idx === (currentChapter || 0) + 1)}
                className="p-1.5 hover:bg-white/10 rounded-full disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
                </svg>
              </button>
            </div>
          </div>

          {/* Stats bar */}
          <div className="px-4 py-2 bg-gray-50 text-xs text-gray-500 flex justify-between">
            <span>{formatDuration(audioStatus.total_duration_ms)} total</span>
            <span>${(audioStatus.total_cost_usd || 0).toFixed(2)}</span>
          </div>
        </div>

        {/* Chapter List (ToC) */}
        <div className="bg-white rounded-lg shadow-sm border">
          <div className="p-3 border-b">
            <h3 className="font-semibold text-gray-900 text-sm">Chapters ({audioChapters.length})</h3>
          </div>
          <div className="divide-y max-h-[calc(100vh-400px)] overflow-y-auto">
            {audioChapters.map((chapter) => (
              <button
                key={chapter.chapter_idx}
                onClick={() => playChapter(chapter.chapter_idx)}
                className={`w-full px-3 py-2 flex items-center justify-between hover:bg-gray-50 transition-colors text-left ${
                  currentChapter === chapter.chapter_idx ? 'bg-blue-50' : ''
                }`}
              >
                <div className="flex items-center space-x-2 min-w-0">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0 ${
                    currentChapter === chapter.chapter_idx
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-600'
                  }`}>
                    {currentChapter === chapter.chapter_idx && isPlaying ? (
                      <span className="animate-pulse">▶</span>
                    ) : (
                      chapter.chapter_idx + 1
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className={`text-sm font-medium truncate ${currentChapter === chapter.chapter_idx ? 'text-blue-600' : 'text-gray-900'}`}>
                      {chapter.title || `Chapter ${chapter.chapter_idx + 1}`}
                    </div>
                    <div className="text-xs text-gray-500">
                      {formatDuration(chapter.duration_ms)}
                    </div>
                  </div>
                </div>
                <a
                  href={chapter.download_url}
                  onClick={(e) => e.stopPropagation()}
                  download
                  className="p-1 text-gray-400 hover:text-gray-600 flex-shrink-0"
                  title="Download"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                </a>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Right side: Chapter Text Reader */}
      <div className="flex-1 min-w-0">
        <div className="bg-white rounded-lg shadow-sm border h-[calc(100vh-200px)] flex flex-col">
          {currentChapter === null ? (
            <div className="flex-1 flex items-center justify-center text-gray-400">
              <div className="text-center">
                <svg className="w-16 h-16 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                </svg>
                <p className="text-lg">Select a chapter to start listening</p>
                <p className="text-sm mt-1">The text will appear here as you listen</p>
              </div>
            </div>
          ) : (
            <>
              {/* Chapter header */}
              <div className="p-4 border-b flex-shrink-0">
                <div className="flex items-center justify-between">
                  <div>
                    {currentChapterText?.entry_number && (
                      <span className="text-sm text-gray-500">{currentChapterText.entry_number}</span>
                    )}
                    <h2 className="text-xl font-semibold text-gray-900">
                      {currentChapterText?.title || currentChapterAudio?.title || `Chapter ${currentChapter + 1}`}
                    </h2>
                    {currentChapterText?.level_name && (
                      <span className="text-sm text-gray-500">{currentChapterText.level_name}</span>
                    )}
                  </div>
                  {isPlaying && (
                    <div className="flex items-center space-x-1 text-blue-600">
                      <span className="animate-pulse">●</span>
                      <span className="text-sm">Playing</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Chapter text content */}
              <div
                ref={textContainerRef}
                className="flex-1 overflow-y-auto p-6"
              >
                {currentChapterText?.polished_text ? (
                  <div className="prose prose-lg max-w-none">
                    {currentChapterText.polished_text.split('\n\n').map((paragraph, idx) => (
                      <p key={idx} className="mb-4 text-gray-800 leading-relaxed">
                        {paragraph}
                      </p>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-gray-400 py-8">
                    <p>No text available for this chapter</p>
                    <p className="text-sm mt-1">The polished text hasn't been generated yet</p>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

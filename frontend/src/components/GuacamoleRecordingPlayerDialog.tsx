"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Guacamole from "guacamole-common-js";
import type { GuacamoleRecordingEntry } from "@/hooks/useGuacamole";
import { withAuthHeaders } from "@/lib/auth";

type SessionRecordingInstance = InstanceType<typeof Guacamole.SessionRecording>;

function formatBytes(value?: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }

  if (value < 1024) {
    return `${value} B`;
  }

  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }

  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatPlaybackTime(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) {
    return "0:00";
  }

  const totalSeconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const remainder = totalSeconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function GuacamoleRecordingPlayerDialog({
  entry,
  open,
  onClose,
}: {
  entry: GuacamoleRecordingEntry | null;
  open: boolean;
  onClose: () => void;
}) {
  const displayHostRef = useRef<HTMLDivElement | null>(null);
  const recordingRef = useRef<SessionRecordingInstance | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [position, setPosition] = useState(0);
  const [seeking, setSeeking] = useState(false);
  const [seekDraft, setSeekDraft] = useState("0");

  const metadata = useMemo(() => {
    if (!entry) {
      return [] as string[];
    }

    return [
      entry.agent_id ? `Agent: ${entry.agent_id}` : "Agent: -",
      entry.username ? `User: ${entry.username}` : "User: -",
      `Size: ${formatBytes(entry.size_bytes ?? null)}`,
    ];
  }, [entry]);

  useEffect(() => {
    setSeekDraft(String(position));
  }, [position]);

  useEffect(() => {
    if (!open || !entry) {
      return;
    }

    let disposed = false;
    const abortController = new AbortController();

    const cleanupRecording = () => {
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      const activeRecording = recordingRef.current;
      recordingRef.current = null;
      if (activeRecording) {
        try {
          activeRecording.pause();
          activeRecording.cancel();
          activeRecording.abort();
          activeRecording.disconnect();
        } catch {
          // Ignore teardown failures from partially initialized recordings.
        }
      }
      if (displayHostRef.current) {
        displayHostRef.current.replaceChildren();
      }
    };

    setLoading(true);
    setReady(false);
    setPlaying(false);
    setError(null);
    setDuration(0);
    setPosition(0);
    setSeekDraft("0");

    const fitDisplayToHost = (activeRecording: SessionRecordingInstance) => {
      const host = displayHostRef.current;
      if (!host) {
        return;
      }

      const display = activeRecording.getDisplay();
      const displayWidth = display.getWidth();
      const displayHeight = display.getHeight();
      if (!displayWidth || !displayHeight || !host.clientWidth || !host.clientHeight) {
        return;
      }

      const scale = Math.max(
        Math.min(host.clientWidth / displayWidth, host.clientHeight / displayHeight),
        0.1,
      );
      display.scale(scale);
    };

    void (async () => {
      try {
        const response = await fetch(entry.download_url, {
          headers: withAuthHeaders(),
          signal: abortController.signal,
        });

        if (!response.ok) {
          throw new Error(`Recording fetch failed with HTTP ${response.status}`);
        }

        const recordingBlob = await response.blob();
        if (disposed) {
          return;
        }

        cleanupRecording();
        const nextRecording = new Guacamole.SessionRecording(recordingBlob);
        recordingRef.current = nextRecording;

        const displayElement = nextRecording.getDisplay().getElement();
        displayElement.classList.add("max-w-full");
        displayHostRef.current?.replaceChildren(displayElement);
        if (displayHostRef.current && typeof ResizeObserver !== "undefined") {
          resizeObserverRef.current = new ResizeObserver(() => {
            fitDisplayToHost(nextRecording);
          });
          resizeObserverRef.current.observe(displayHostRef.current);
        }

        nextRecording.onprogress = (nextDuration) => {
          if (!disposed) {
            setDuration(nextDuration);
          }
        };

        nextRecording.onload = () => {
          if (disposed) {
            return;
          }
          nextRecording.seek(0, () => {
            if (disposed) {
              return;
            }
            setLoading(false);
            setReady(true);
            setDuration(nextRecording.getDuration());
            setPosition(nextRecording.getPosition());
            fitDisplayToHost(nextRecording);
          });
        };

        nextRecording.onplay = () => {
          if (!disposed) {
            setPlaying(true);
          }
        };

        nextRecording.onpause = () => {
          if (!disposed) {
            setPlaying(false);
            setPosition(nextRecording.getPosition());
          }
        };

        nextRecording.onseek = (nextPosition) => {
          if (!disposed) {
            setPosition(nextPosition);
            fitDisplayToHost(nextRecording);
          }
        };

        nextRecording.onerror = (message) => {
          if (!disposed) {
            setLoading(false);
            setError(message || "Playback failed.");
          }
        };

        nextRecording.onabort = () => {
          if (!disposed) {
            setPlaying(false);
          }
        };
      } catch (fetchError) {
        if (disposed || abortController.signal.aborted) {
          return;
        }
        setLoading(false);
        setError(fetchError instanceof Error ? fetchError.message : "Playback failed.");
      }
    })();

    return () => {
      disposed = true;
      abortController.abort();
      cleanupRecording();
    };
  }, [entry, open]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const intervalId = window.setInterval(() => {
      const activeRecording = recordingRef.current;
      if (!activeRecording || seeking) {
        return;
      }
      setPosition(activeRecording.getPosition());
      setDuration(activeRecording.getDuration());
      setPlaying(activeRecording.isPlaying());
    }, 200);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [open, seeking]);

  if (!open || !entry) {
    return null;
  }

  const maxDuration = Math.max(duration, 0);

  const commitSeek = () => {
    const activeRecording = recordingRef.current;
    if (!activeRecording) {
      setSeeking(false);
      return;
    }

    const nextPosition = Math.min(Math.max(Number(seekDraft) || 0, 0), maxDuration || 0);
    activeRecording.seek(nextPosition, () => {
      setPosition(activeRecording.getPosition());
      setDuration(activeRecording.getDuration());
      setSeeking(false);
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div className="flex h-[min(92vh,56rem)] w-full max-w-6xl flex-col overflow-hidden rounded-3xl border border-slate-700 bg-slate-950 shadow-2xl shadow-black/50">
        <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-6 py-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-300">Recording Playback</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-100">{entry.name || entry.relative_path}</h2>
            <p className="mt-2 text-xs text-slate-500">{metadata.join("  •  ")}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-medium text-slate-300 hover:border-slate-500 hover:text-slate-100"
          >
            Close
          </button>
        </div>

        <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="relative min-h-[20rem] bg-[radial-gradient(circle_at_top,#0f2741_0%,rgba(2,6,23,0.98)_52%,rgba(2,6,23,1)_100%)]">
            <div ref={displayHostRef} className="flex h-full min-h-[20rem] items-center justify-center overflow-auto p-6" />
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-950/60 text-sm text-slate-300">
                Loading recording...
              </div>
            )}
            {error && (
              <div className="absolute inset-x-6 bottom-6 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                {error}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-5 border-l border-slate-800 bg-slate-900/82 px-5 py-5">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Status</p>
              <p className="mt-2 text-sm text-slate-200">
                {error ? "Playback error" : loading ? "Preparing player" : ready ? (playing ? "Playing" : "Ready") : "Waiting for data"}
              </p>
            </div>

            <div className="grid gap-3">
              <button
                type="button"
                disabled={!ready}
                onClick={() => {
                  const activeRecording = recordingRef.current;
                  if (!activeRecording) {
                    return;
                  }
                  if (activeRecording.isPlaying()) {
                    activeRecording.pause();
                  } else {
                    activeRecording.play();
                  }
                }}
                className="rounded-xl border border-cyan-500/30 bg-cyan-500/12 px-4 py-3 text-sm font-medium text-cyan-100 disabled:cursor-not-allowed disabled:border-slate-800 disabled:bg-slate-900 disabled:text-slate-500"
              >
                {playing ? "Pause" : "Play"}
              </button>

              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  disabled={!ready}
                  onClick={() => {
                    const activeRecording = recordingRef.current;
                    if (!activeRecording) {
                      return;
                    }
                    const nextPosition = Math.max(activeRecording.getPosition() - 5000, 0);
                    activeRecording.seek(nextPosition, () => {
                      setPosition(activeRecording.getPosition());
                    });
                  }}
                  className="rounded-xl border border-slate-700 px-4 py-3 text-sm text-slate-200 disabled:cursor-not-allowed disabled:text-slate-500"
                >
                  -5s
                </button>
                <button
                  type="button"
                  disabled={!ready}
                  onClick={() => {
                    const activeRecording = recordingRef.current;
                    if (!activeRecording) {
                      return;
                    }
                    const nextPosition = Math.min(activeRecording.getPosition() + 5000, activeRecording.getDuration());
                    activeRecording.seek(nextPosition, () => {
                      setPosition(activeRecording.getPosition());
                    });
                  }}
                  className="rounded-xl border border-slate-700 px-4 py-3 text-sm text-slate-200 disabled:cursor-not-allowed disabled:text-slate-500"
                >
                  +5s
                </button>
              </div>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
                <span>{formatPlaybackTime(position)}</span>
                <span>{formatPlaybackTime(duration)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={maxDuration || 0}
                step={1000}
                value={Math.min(Number(seekDraft) || 0, maxDuration || 0)}
                disabled={!ready || maxDuration <= 0}
                onChange={(event) => {
                  setSeeking(true);
                  setSeekDraft(event.target.value);
                }}
                onMouseUp={commitSeek}
                onTouchEnd={commitSeek}
                className="w-full accent-cyan-400"
              />
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-xs text-slate-400">
              <p className="font-semibold uppercase tracking-[0.18em] text-slate-500">Path</p>
              <p className="mt-2 break-all font-mono">{entry.relative_path}</p>
              <p className="mt-4 text-slate-500">
                Guacamole recordings are protocol replays, not video files. Playback is rendered directly in the browser from the `.guac` stream.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

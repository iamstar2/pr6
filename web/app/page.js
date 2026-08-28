'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { getSocket, SOCKET_URL } from '../lib/socket';
import { playViolationBeep } from '../lib/beep';
import ThemeToggle from '../components/ThemeToggle';
import SoundToggle from '../components/SoundToggle';
import LiveDetectionView from '../components/LiveDetectionView';
import ViolationToast from '../components/ViolationToast';
import ViolationHistory from '../components/ViolationHistory';
import ImageLightbox from '../components/ImageLightbox';
import StatsSummary from '../components/StatsSummary';

const MAX_HISTORY = 50;
const SOUND_PREF_KEY = 'violationSoundEnabled';

export default function DashboardPage() {
  const [connected, setConnected] = useState(false);
  const [liveFrame, setLiveFrame] = useState(null);
  const [history, setHistory] = useState([]);
  const [toast, setToast] = useState(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [lightboxUrl, setLightboxUrl] = useState(null);
  const [totalDetections, setTotalDetections] = useState(0);
  const toastCounter = useRef(0);
  const soundEnabledRef = useRef(true);

  // Load persisted sound preference once on mount.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(SOUND_PREF_KEY);
      if (stored !== null) {
        const val = stored === 'true';
        setSoundEnabled(val);
        soundEnabledRef.current = val;
      }
    } catch (e) {
      // ignore - default stays true
    }
  }, []);

  const handleSoundChange = useCallback((val) => {
    setSoundEnabled(val);
    soundEnabledRef.current = val;
    try {
      window.localStorage.setItem(SOUND_PREF_KEY, String(val));
    } catch (e) {
      // ignore
    }
  }, []);

  const dismissToast = useCallback((key) => {
    setToast((current) => (current && current.key === key ? null : current));
  }, []);

  useEffect(() => {
    const socket = getSocket();

    const onConnect = () => setConnected(true);
    const onDisconnect = () => setConnected(false);

    const onLiveFrame = (payload) => {
      setLiveFrame(payload);
      setTotalDetections((n) => n + 1);
    };

    const onViolation = (payload) => {
      // 1) append to history (newest first, capped)
      setHistory((prev) => {
        const next = [
          {
            ...payload,
            cloudStatus: 'pending',
            image_url: '',
          },
          ...prev.filter((item) => item.request_id !== payload.request_id),
        ];
        return next.slice(0, MAX_HISTORY);
      });

      // 2) show toast/banner
      toastCounter.current += 1;
      setToast({ ...payload, key: `${payload.request_id || 'v'}-${toastCounter.current}` });

      // 3) optional beep
      if (soundEnabledRef.current) {
        playViolationBeep();
      }

      // Also treat a violation as a live frame update so the overlay reflects it.
      setLiveFrame(payload);
    };

    const onCloudStatus = (payload) => {
      setHistory((prev) =>
        prev.map((item) =>
          item.request_id === payload.request_id
            ? { ...item, cloudStatus: payload.status === 'success' ? 'success' : 'failed', image_url: payload.image_url || '' }
            : item
        )
      );
    };

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('live_detection_frame', onLiveFrame);
    socket.on('violation_detected', onViolation);
    socket.on('cloud_upload_status', onCloudStatus);

    setConnected(socket.connected);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('live_detection_frame', onLiveFrame);
      socket.off('violation_detected', onViolation);
      socket.off('cloud_upload_status', onCloudStatus);
    };
  }, []);

  return (
    <div className="min-h-screen">
      <header className="glass-header sticky top-0 z-40 px-6 py-4 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-on-surface">⚠️ 안전 위반 모니터링</h1>
          <span
            className="pill"
            style={{
              backgroundColor: connected ? 'var(--color-success)' : 'var(--color-error)',
              color: connected ? 'var(--color-on-success)' : 'var(--color-on-error)',
            }}
            title={SOCKET_URL}
          >
            <span>{connected ? '●' : '○'}</span>
            <span>{connected ? '연결됨' : '연결 끊김'}</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <SoundToggle enabled={soundEnabled} onChange={handleSoundChange} />
          <ThemeToggle />
        </div>
      </header>

      <main className="max-w-container mx-auto px-6 py-8 flex flex-col gap-8">
        <div className="flex flex-col lg:flex-row gap-8 items-stretch">
          <div className="w-full lg:flex-1 lg:min-w-0 lg:h-[640px]">
            <LiveDetectionView frame={liveFrame} onImageClick={setLightboxUrl} />
          </div>
          <div className="w-full lg:flex-1 lg:min-w-0 lg:h-[640px]">
            <ViolationHistory items={history} onImageClick={setLightboxUrl} />
          </div>
        </div>

        <StatsSummary items={history} totalDetections={totalDetections} />
      </main>

      <ViolationToast toast={toast} onDismiss={dismissToast} />
      <ImageLightbox url={lightboxUrl} onClose={() => setLightboxUrl(null)} />
    </div>
  );
}

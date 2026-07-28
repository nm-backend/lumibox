/* LumiBox HLS Player — Netflix-level player */
(function () {
    "use strict";

    const root = document.querySelector("[data-stream-player]");
    const configNode = document.getElementById("stream-player-config");
    if (!root || !configNode) return;

    const config = JSON.parse(configNode.textContent);
    const video = root.querySelector("[data-player-video]");
    const stage = root.querySelector("[data-player-stage]");
    const statusEl = root.querySelector("[data-player-status]");
    const progress = root.querySelector("[data-player-progress]");
    const buffer = root.querySelector("[data-player-buffer]");
    const time = root.querySelector("[data-player-time]");
    const quality = root.querySelector("[data-player-quality]");
    const speed = root.querySelector("[data-player-speed]");
    const subtitles = root.querySelector("[data-player-subtitles]");
    const introButton = root.querySelector('[data-player-skip="intro"]');
    const recapButton = root.querySelector('[data-player-skip="recap"]');
    const nextPanel = root.querySelector("[data-player-next]");
    const nextCountdown = root.querySelector("[data-player-countdown]");
    const nextTitle = root.querySelector("[data-player-next-title]");
    const nextLink = root.querySelector("[data-player-next-link]");
    const muteBtn = root.querySelector("[data-player-mute]");
    const volumeRange = root.querySelector("[data-player-volume]");
    const centerPlay = root.querySelector("[data-player-center-play]");
    const centerIcon = root.querySelector("[data-player-center-icon]");
    const shortcutsPanel = root.querySelector("[data-player-shortcuts]");
    const screenshotBtn = root.querySelector("[data-player-screenshot]");
    const helpBtn = root.querySelector("[data-player-help]");

    let hls = null;
    let savedPosition = 0;
    let nextTimer = null;
    let resumed = false;
    let controlsTimer = null;
    let cursorTimer = null;
    let hlsRecoveryAttempts = 0;
    const MAX_HLS_RECOVERY = 3;

    /* ---------- Helpers ---------- */

    const setStatus = (message) => {
        statusEl.textContent = message;
        statusEl.hidden = !message;
    };

    const formatTime = (seconds) => {
        const value = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
        const hours = Math.floor(value / 3600);
        const minutes = Math.floor((value % 3600) / 60);
        const remaining = value % 60;
        return hours
            ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`
            : `${minutes}:${String(remaining).padStart(2, "0")}`;
    };

    const formatResolutionLabel = (height) => {
        if (height >= 2160) return '4K';
        if (height >= 1440) return '1440p';
        if (height >= 1080) return '1080p';
        if (height >= 720) return '720p';
        if (height >= 480) return '480p';
        if (height >= 360) return '360p';
        return `${height}p`;
    };

    const getCookie = (name) => {
        const parts = (`; ${document.cookie}`).split(`; ${name}=`);
        return parts.length === 2 ? decodeURIComponent(parts.pop().split(";").shift()) : "";
    };

    const setPlayButtons = () => {
        const isPaused = video.paused;
        root.classList.toggle("stream-player--playing", !isPaused);
        root.querySelectorAll("[data-player-toggle]").forEach((btn) => {
            btn.textContent = isPaused ? "▶" : "❚❚";
            btn.setAttribute("aria-label", isPaused ? "Воспроизвести" : "Пауза");
        });
    };

    /* ---------- Show controls on mouse move ---------- */

    const showControls = () => {
        stage.classList.add("stream-player__stage--active");
        window.clearTimeout(controlsTimer);
        if (!video.paused) {
            controlsTimer = window.setTimeout(() => {
                stage.classList.remove("stream-player__stage--active");
            }, 3000);
        }
    };

    const hideControlsNow = () => {
        stage.classList.remove("stream-player__stage--active");
        stage.style.cursor = "none";
        window.clearTimeout(controlsTimer);
        window.clearTimeout(cursorTimer);
    };

    stage.addEventListener("mousemove", showControls);
    stage.addEventListener("mouseleave", () => {
        if (!video.paused) hideControlsNow();
    });
    stage.addEventListener("touchstart", () => {
        stage.classList.toggle("stream-player__stage--active");
        window.clearTimeout(controlsTimer);
    });

    /* ---------- Volume ---------- */

    const updateVolumeUI = () => {
        const isMuted = video.muted || video.volume === 0;
        video.muted = isMuted || video.volume === 0;
        muteBtn.textContent = isMuted ? "🔇" : video.volume > 0.5 ? "🔊" : "🔉";
        muteBtn.setAttribute("aria-label", isMuted ? "Включить звук" : "Выключить звук");
        volumeRange.value = isMuted ? 0 : video.volume;
    };

    muteBtn.addEventListener("click", () => {
        video.muted = !video.muted;
        if (!video.muted && video.volume === 0) video.volume = 0.5;
        updateVolumeUI();
        showControls();
    });

    volumeRange.addEventListener("input", () => {
        video.muted = false;
        video.volume = parseFloat(volumeRange.value);
        updateVolumeUI();
    });

    video.addEventListener("volumechange", updateVolumeUI);

    /* ---------- Quality ---------- */

    const updateQualityFromHls = () => {
        if (!hls || !quality) return;
        const level = hls.currentLevel;
        if (level < 0) {
            quality.value = "auto";
            return;
        }
        const levelInfo = hls.levels[level];
        if (levelInfo) {
            const label = formatResolutionLabel(levelInfo.height);
            if ([...quality.options].some(opt => opt.value === label)) {
                quality.value = label;
            }
        }
    };

    const setQualityOptions = () => {
        if (hls && hls.levels && hls.levels.length) {
            const seen = new Set(['auto']);
            const items = ['auto', ...hls.levels
                .map(l => formatResolutionLabel(l.height))
                .filter(label => {
                    if (seen.has(label)) return false;
                    seen.add(label);
                    return true;
                })
            ];
            quality.replaceChildren(
                ...items.map((value) => {
                    const opt = new Option(
                        value === "auto" ? "Авто" : value,
                        value,
                        false,
                        value === (config.defaultQuality === 'auto' ? 'auto' : formatResolutionLabel(parseInt(config.defaultQuality, 10)))
                    );
                    return opt;
                })
            );
            return;
        }
        // Fallback: use configured qualities
        const values = [...new Set(["auto", ...(config.qualities || [])])];
        quality.replaceChildren(
            ...values.map((value) => {
                const label = value === "auto" ? "Авто" : value;
                const opt = new Option(label, value, false, value === (config.defaultQuality || 'auto'));
                return opt;
            })
        );
    };

    const setAdaptiveQuality = () => {
        if (!hls) return;
        if (quality.value === "auto") {
            hls.currentLevel = -1;
            return;
        }
        // Find level by resolution label
        const targetHeight = parseInt(quality.value, 10);
        if (isNaN(targetHeight)) return;
        const level = hls.levels.findIndex(
            (item) => item.height === targetHeight
        );
        if (level >= 0) hls.currentLevel = level;
    };

    /* ---------- Subtitles ---------- */

    const setSubtitleOptions = () => {
        (config.subtitleTracks || []).forEach((track) => {
            const el = document.createElement("track");
            el.kind = track.kind === "captions" ? "captions" : "subtitles";
            el.srclang = track.language;
            el.label = track.label;
            el.src = track.url;
            el.default = track.default || track.language === config.subtitlesLanguage;
            video.append(el);
            subtitles.append(new Option(track.label, track.id, false, el.default));
        });
    };

    const selectSubtitle = (trackId) => {
        [...video.textTracks].forEach((track, index) => {
            track.mode =
                trackId !== "off" && config.subtitleTracks[index]?.id === trackId
                    ? "showing"
                    : "disabled";
        });
    };

    /* ---------- HLS Error Recovery ---------- */

    const recoverHlsError = (data) => {
        if (!data.fatal) return;

        hlsRecoveryAttempts += 1;

        if (data.type === window.Hls.ErrorTypes.NETWORK_ERROR && hlsRecoveryAttempts <= MAX_HLS_RECOVERY) {
            setStatus(`Проблема с сетью. Повторная попытка ${hlsRecoveryAttempts}/${MAX_HLS_RECOVERY}…`);
            hls.startLoad();
            return;
        }

        if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR && hlsRecoveryAttempts <= MAX_HLS_RECOVERY) {
            setStatus(`Восстановление… ${hlsRecoveryAttempts}/${MAX_HLS_RECOVERY}`);
            hls.recoverMediaError();
            return;
        }

        // Fatal: try level fallback
        if (hls.levels && hls.currentLevel > 0) {
            setStatus("Переключение на более низкое качество…");
            hls.currentLevel = Math.max(0, hls.currentLevel - 1);
            hls.startLoad();
            return;
        }

        setStatus("Не удалось загрузить видео. Попробуйте позже.");
    };

    /* ---------- Source loading ---------- */

    const attachSource = () => {
        const source = config.source;
        if (!source?.url) {
            setStatus("Источник видео пока недоступен.");
            return;
        }

        root.classList.add("stream-player--loading");

        if (source.type === "hls" && video.canPlayType("application/vnd.apple.mpegurl")) {
            // Safari native HLS
            video.src = source.url;
            setStatus("");
            return;
        }

        if (source.type === "hls" && window.Hls?.isSupported()) {
            hls = new window.Hls({
                enableWorker: true,
                capLevelToPlayerSize: true,
                backbufferLength: 30,
                maxBufferLength: 30,
            });
            hlsRecoveryAttempts = 0;
            hls.loadSource(source.url);
            hls.attachMedia(video);
            hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
                root.classList.remove("stream-player--loading");
                setQualityOptions();
                setAdaptiveQuality();
                video.play().catch(() => {});
            });
            hls.on(window.Hls.Events.LEVEL_SWITCHED, (_event, data) => {
                const levelInfo = hls.levels[data.level];
                if (levelInfo) {
                    updateQualityFromHls();
                }
            });
            hls.on(window.Hls.Events.ERROR, recoverHlsError);
            setStatus("");
            return;
        }

        if (source.type === "dash" && window.dashjs) {
            window.dashjs.MediaPlayer().create().initialize(video, source.url, false);
            setStatus("");
            return;
        }

        if (source.type === "mp4") {
            video.src = source.url;
            setStatus("");
            return;
        }

        setStatus("Для этого формата нужен HLS.js или DASH-адаптер.");
    };

    /* ---------- Progress saving ---------- */

    const saveProgress = (completed = false) => {
        if (!config.progressUrl || !video.duration || !Number.isFinite(video.currentTime)) return;
        const position = Math.floor(video.currentTime);
        if (!completed && Math.abs(position - savedPosition) < 15) return;
        savedPosition = position;
        fetch(config.progressUrl, {
            method: "POST",
            credentials: "same-origin",
            keepalive: true,
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: JSON.stringify({
                asset_id: config.assetId,
                position_seconds: position,
                is_completed: completed,
            }),
        }).catch(() => undefined);
    };

    /* ---------- Timeline ---------- */

    const markerActive = (marker) =>
        marker && video.currentTime >= marker.start && video.currentTime < marker.end;

    const updateTimeline = () => {
        const duration = video.duration || config.duration || 0;
        progress.max = duration;
        progress.value = video.currentTime || 0;
        time.textContent = `${formatTime(video.currentTime)} / ${formatTime(duration)}`;

        if (video.buffered.length && duration) {
            const bufferedEnd = video.buffered.end(video.buffered.length - 1);
            buffer.style.setProperty(
                "--buffered",
                `${Math.min(100, (bufferedEnd * 100) / duration)}%`
            );
        }

        introButton.hidden = !markerActive(config.intro);
        recapButton.hidden = !markerActive(config.recap);
    };

    /* ---------- Next episode countdown ---------- */

    const stopNextCountdown = () => {
        window.clearInterval(nextTimer);
        nextTimer = null;
        nextPanel.hidden = true;
    };

    const startNextCountdown = () => {
        if (!config.nextEpisode || !config.autoplayNext) return;
        let remaining = 15;
        nextTitle.textContent = config.nextEpisode.title;
        nextLink.href = config.nextEpisode.url;
        nextCountdown.textContent = remaining;
        nextPanel.hidden = false;
        nextTimer = window.setInterval(() => {
            remaining -= 1;
            nextCountdown.textContent = String(remaining);
            if (remaining <= 0) {
                window.clearInterval(nextTimer);
                window.location.assign(config.nextEpisode.url);
            }
        }, 1000);
    };

    /* ---------- Center play flash ---------- */

    const showCenterIcon = (icon) => {
        centerIcon.textContent = icon;
        centerPlay.hidden = false;
        centerPlay.style.animation = "none";
        // Force reflow
        void centerPlay.offsetHeight;
        centerPlay.style.animation = "centerPlayFade 0.5s ease forwards";
        window.setTimeout(() => {
            centerPlay.hidden = true;
        }, 500);
    };

    /* ---------- Screenshot ---------- */

    const takeScreenshot = () => {
        try {
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(video, 0, 0);
            canvas.toBlob((blob) => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `lumibox-${config.assetId}-${Math.floor(Date.now() / 1000)}.png`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            });
            // Flash effect
            const flash = document.createElement("div");
            flash.className = "stream-player__screenshot-flash";
            stage.appendChild(flash);
            window.setTimeout(() => flash.remove(), 300);
        } catch {
            // Silently fail if screenshot isn't possible
        }
    };

    /* ---------- Seek ---------- */

    const seek = (seconds) => {
        video.currentTime = Math.max(
            0,
            Math.min(video.duration || config.duration, video.currentTime + seconds)
        );
        showControls();
    };

    /* ---------- Event wiring ---------- */

    // Play/pause toggle on all toggle buttons
    root.querySelectorAll("[data-player-toggle]").forEach((btn) =>
        btn.addEventListener("click", () => {
            if (video.paused) {
                video.play();
                showCenterIcon("▶");
            } else {
                video.pause();
                showCenterIcon("❚❚");
            }
        })
    );

    // Seek buttons
    root.querySelectorAll("[data-player-seek]").forEach((btn) =>
        btn.addEventListener("click", () => seek(Number(btn.dataset.playerSeek)))
    );

    // Skip buttons (intro/recap)
    root.querySelectorAll("[data-player-skip]").forEach((btn) =>
        btn.addEventListener("click", () => {
            const marker = config[btn.dataset.playerSkip];
            if (marker) video.currentTime = marker.end;
        })
    );

    // Progress bar
    // Progress bar — show preview time on hover
    let tooltipTimer = null;
    const tooltip = root.querySelector("[data-player-tooltip]");

    progress.addEventListener("input", () => {
        video.currentTime = Number(progress.value);
    });

    progress.addEventListener("mouseenter", () => {
        tooltip.hidden = false;
    });

    progress.addEventListener("mouseleave", () => {
        tooltip.hidden = true;
    });

    progress.addEventListener("mousemove", (e) => {
        const rect = progress.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        const hoverTime = ratio * (video.duration || config.duration || 0);
        tooltip.textContent = formatTime(hoverTime);
        tooltip.style.left = `${ratio * 100}%`;
    });

    // Speed
    const speedToast = root.querySelector("[data-player-speed-toast]");
    let speedToastTimer = null;

    const showSpeedToast = (value) => {
        if (!speedToast) return;
        speedToast.textContent = `${value}×`;
        speedToast.hidden = false;
        speedToast.classList.remove('stream-player__speed-toast--out');
        void speedToast.offsetHeight;
        window.clearTimeout(speedToastTimer);
        speedToastTimer = window.setTimeout(() => {
            speedToast.classList.add('stream-player__speed-toast--out');
            window.setTimeout(() => { speedToast.hidden = true; }, 300);
        }, 1200);
    };

    speed.addEventListener("change", () => {
        video.playbackRate = Number(speed.value);
        showSpeedToast(speed.value);
    });

    // Quality
    quality.addEventListener("change", setAdaptiveQuality);

    // Subtitles
    subtitles.addEventListener("change", () => selectSubtitle(subtitles.value));

    // PiP
    root.querySelector("[data-player-pip]").addEventListener("click", async () => {
        if (document.pictureInPictureElement) {
            await document.exitPictureInPicture();
        } else if (document.pictureInPictureEnabled) {
            await video.requestPictureInPicture();
        }
    });

    // Toggle fullscreen helper
    const toggleFullscreen = async () => {
        if (document.fullscreenElement) {
            await document.exitFullscreen();
        } else {
            await stage.requestFullscreen();
        }
        showControls();
    };

    root.querySelector("[data-player-fullscreen]").addEventListener("click", toggleFullscreen);

    // Double-click to toggle fullscreen (Netflix standard)
    stage.addEventListener("dblclick", (e) => {
        // Don't toggle if clicking controls
        if (e.target.closest(".stream-player__controls")) return;
        toggleFullscreen();
    });

    // Cancel next
    root.querySelector("[data-player-cancel-next]").addEventListener("click", stopNextCountdown);

    // Screenshot
    screenshotBtn.addEventListener("click", takeScreenshot);

    // Help / shortcuts
    helpBtn.addEventListener("click", () => {
        shortcutsPanel.hidden = !shortcutsPanel.hidden;
    });

    root.querySelector("[data-shortcuts-close]").addEventListener("click", () => {
        shortcutsPanel.hidden = true;
    });

    // Click on stage to toggle play/pause
    stage.addEventListener("click", (e) => {
        if (e.target.closest(".stream-player__controls") || e.target.closest(".stream-player__skip-actions") || e.target.closest(".stream-player__next") || e.target.closest(".stream-player__shortcuts") || e.target.closest(".stream-player__big-play")) return;
        if (video.paused) {
            video.play();
            showCenterIcon("▶");
        } else {
            video.pause();
            showCenterIcon("❚❚");
        }
        showControls();
    });

    // Fullscreen change — update controls visibility
    document.addEventListener("fullscreenchange", () => {
        if (document.fullscreenElement) {
            showControls();
            window.setTimeout(showControls, 100);
        }
    });

    /* ---------- Video events ---------- */

    video.addEventListener("loadedmetadata", () => {
        root.classList.remove("stream-player--loading");
        if (!resumed && config.resumeAt > 0 && config.resumeAt < video.duration - 15) {
            video.currentTime = config.resumeAt;
            // Show a brief "Resuming" indicator
            setStatus(`Продолжить с ${formatTime(config.resumeAt)}`);
            window.setTimeout(() => setStatus(""), 2500);
        }
        resumed = true;
        speed.value = String(config.defaultSpeed);
        video.playbackRate = Number(config.defaultSpeed);
        selectSubtitle(subtitles.value);
        updateTimeline();
        updateVolumeUI();
    });

    video.addEventListener("play", () => {
        stopNextCountdown();
        setPlayButtons();
        showControls();
    });

    video.addEventListener("pause", () => {
        setPlayButtons();
        saveProgress();
        stage.classList.add("stream-player__stage--active");
        window.clearTimeout(controlsTimer);
    });

    video.addEventListener("timeupdate", () => {
        updateTimeline();
        saveProgress();
    });

    video.addEventListener("ended", () => {
        saveProgress(true);
        setPlayButtons();
        root.classList.remove("stream-player--loading");
        startNextCountdown();
        stage.classList.add("stream-player__stage--active");
    });

    video.addEventListener("waiting", () => {
        setStatus("Буферизация…");
        root.classList.add("stream-player--loading");
    });
    video.addEventListener("playing", () => {
        setStatus("");
        root.classList.remove("stream-player--loading");
    });
    video.addEventListener("canplay", () => {
        setStatus("");
        root.classList.remove("stream-player--loading");
    });

    video.addEventListener("error", () => {
        const error = video.error;
        if (error) {
            const messages = {
                1: "Загрузка видео прервана.",
                2: "Ошибка сети. Проверьте подключение.",
                3: "Не удалось декодировать видео.",
                4: "Формат видео не поддерживается.",
            };
            setStatus(messages[error.code] || "Не удалось воспроизвести видео.");
        } else {
            setStatus("Не удалось воспроизвести видео.");
        }
    });

    /* ---------- Page lifecycle ---------- */

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) saveProgress();
    });

    window.addEventListener("pagehide", () => saveProgress());

    /* ---------- Cursor auto-hide ---------- */

    const showCursor = () => {
        stage.style.cursor = "default";
        window.clearTimeout(cursorTimer);
        if (!video.paused) {
            cursorTimer = window.setTimeout(() => {
                stage.style.cursor = "none";
            }, 2500);
        }
    };

    stage.addEventListener("mousemove", showCursor);
    stage.addEventListener("mousedown", showCursor);

    /* ---------- Keyboard shortcuts ---------- */

    document.addEventListener("keydown", (event) => {
        if (event.target.matches("input, select, textarea") || event.target.isContentEditable) return;

        switch (event.code) {
            case "Space":
                event.preventDefault();
                if (video.paused) {
                    video.play();
                    showCenterIcon("▶");
                } else {
                    video.pause();
                    showCenterIcon("❚❚");
                }
                break;
            case "ArrowLeft":
                event.preventDefault();
                seek(-10);
                showCenterIcon("↶ 10");
                break;
            case "ArrowRight":
                event.preventDefault();
                seek(10);
                showCenterIcon("10 ↷");
                break;
            case "ArrowUp":
                event.preventDefault();
                video.volume = Math.min(1, video.volume + 0.1);
                updateVolumeUI();
                break;
            case "ArrowDown":
                event.preventDefault();
                video.volume = Math.max(0, video.volume - 0.1);
                updateVolumeUI();
                break;
            case "KeyM":
                video.muted = !video.muted;
                updateVolumeUI();
                break;
            case "KeyF":
                toggleFullscreen();
                break;
            case "KeyP":
                if (document.pictureInPictureElement) {
                    document.exitPictureInPicture();
                } else if (document.pictureInPictureEnabled) {
                    video.requestPictureInPicture();
                }
                break;
            case "KeyS":
                takeScreenshot();
                break;
            case "Slash":
                if (!event.shiftKey) {
                    shortcutsPanel.hidden = !shortcutsPanel.hidden;
                }
                break;
            case "Digit0":
            case "Numpad0":
                event.preventDefault();
                video.currentTime = 0;
                break;
        }
    });

    /* ---------- Init ---------- */

    setQualityOptions();
    setSubtitleOptions();
    attachSource();
    setPlayButtons();
    updateVolumeUI();
})();

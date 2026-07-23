(() => {
    const root = document.querySelector("[data-stream-player]");
    const configNode = document.getElementById("stream-player-config");
    if (!root || !configNode) return;

    const config = JSON.parse(configNode.textContent);
    const video = root.querySelector("[data-player-video]");
    const stage = root.querySelector("[data-player-stage]");
    const status = root.querySelector("[data-player-status]");
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
    let hls = null;
    let savedPosition = 0;
    let nextTimer = null;
    let resumed = false;

    const setStatus = (message) => { status.textContent = message; status.hidden = !message; };
    const formatTime = (seconds) => {
        const value = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
        const hours = Math.floor(value / 3600);
        const minutes = Math.floor((value % 3600) / 60);
        const remaining = value % 60;
        return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}` : `${minutes}:${String(remaining).padStart(2, "0")}`;
    };
    const getCookie = (name) => {
        const parts = (`; ${document.cookie}`).split(`; ${name}=`);
        return parts.length === 2 ? decodeURIComponent(parts.pop().split(";").shift()) : "";
    };
    const setPlayButtons = () => {
        const isPaused = video.paused;
        root.classList.toggle("stream-player--playing", !isPaused);
        root.querySelectorAll("[data-player-toggle]").forEach((button) => {
            button.textContent = isPaused ? "▶" : "❚❚";
            button.setAttribute("aria-label", isPaused ? "Воспроизвести" : "Пауза");
        });
    };
    const setQualityOptions = () => {
        const values = [...new Set(["auto", ...(config.qualities || [])])];
        quality.replaceChildren(...values.map((value) => {
            const option = new Option(value === "auto" ? "Качество: авто" : value, value, false, value === config.defaultQuality);
            return option;
        }));
    };
    const setSubtitleOptions = () => (config.subtitleTracks || []).forEach((track) => {
        const element = document.createElement("track");
        element.kind = track.kind === "captions" ? "captions" : "subtitles";
        element.srclang = track.language;
        element.label = track.label;
        element.src = track.url;
        element.default = track.default || track.language === config.subtitlesLanguage;
        video.append(element);
        subtitles.append(new Option(track.label, track.id, false, element.default));
    });
    const selectSubtitle = (trackId) => [...video.textTracks].forEach((track, index) => {
        track.mode = trackId !== "off" && config.subtitleTracks[index]?.id === trackId ? "showing" : "disabled";
    });
    const setAdaptiveQuality = () => {
        if (!hls) return;
        if (quality.value === "auto") { hls.currentLevel = -1; return; }
        const level = hls.levels.findIndex((item) => item.height === Number.parseInt(quality.value, 10));
        if (level >= 0) hls.currentLevel = level;
    };
    const attachSource = () => {
        const source = config.source;
        if (!source?.url) { setStatus("Источник видео пока недоступен."); return; }
        if (source.type === "hls" && video.canPlayType("application/vnd.apple.mpegurl")) video.src = source.url;
        else if (source.type === "hls" && window.Hls?.isSupported()) {
            hls = new window.Hls({ enableWorker: true, capLevelToPlayerSize: true });
            hls.loadSource(source.url); hls.attachMedia(video);
            hls.on(window.Hls.Events.MANIFEST_PARSED, setAdaptiveQuality);
        } else if (source.type === "dash" && window.dashjs) window.dashjs.MediaPlayer().create().initialize(video, source.url, false);
        else if (source.type === "mp4") video.src = source.url;
        else { setStatus("Для этого формата нужен подключённый HLS/DASH-адаптер."); return; }
        setStatus("");
    };
    const saveProgress = (completed = false) => {
        if (!config.progressUrl || !video.duration || !Number.isFinite(video.currentTime)) return;
        const position = Math.floor(video.currentTime);
        if (!completed && Math.abs(position - savedPosition) < 15) return;
        savedPosition = position;
        fetch(config.progressUrl, { method: "POST", credentials: "same-origin", keepalive: true, headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") }, body: JSON.stringify({ asset_id: config.assetId, position_seconds: position, is_completed: completed }) }).catch(() => undefined);
    };
    const markerActive = (marker) => marker && video.currentTime >= marker.start && video.currentTime < marker.end;
    const updateTimeline = () => {
        const duration = video.duration || config.duration || 0;
        progress.max = duration; progress.value = video.currentTime || 0;
        time.textContent = `${formatTime(video.currentTime)} / ${formatTime(duration)}`;
        if (video.buffered.length && duration) buffer.style.setProperty("--buffered", `${Math.min(100, video.buffered.end(video.buffered.length - 1) * 100 / duration)}%`);
        introButton.hidden = !markerActive(config.intro);
        recapButton.hidden = !markerActive(config.recap);
    };
    const stopNextCountdown = () => { window.clearInterval(nextTimer); nextTimer = null; nextPanel.hidden = true; };
    const startNextCountdown = () => {
        if (!config.nextEpisode || !config.autoplayNext) return;
        let remaining = 15;
        nextTitle.textContent = config.nextEpisode.title; nextLink.href = config.nextEpisode.url; nextCountdown.textContent = remaining; nextPanel.hidden = false;
        nextTimer = window.setInterval(() => { remaining -= 1; nextCountdown.textContent = remaining; if (remaining <= 0) { window.clearInterval(nextTimer); window.location.assign(config.nextEpisode.url); } }, 1000);
    };
    const seek = (seconds) => { video.currentTime = Math.max(0, Math.min(video.duration || config.duration, video.currentTime + seconds)); };

    root.querySelectorAll("[data-player-toggle]").forEach((button) => button.addEventListener("click", () => (video.paused ? video.play() : video.pause())));
    root.querySelectorAll("[data-player-seek]").forEach((button) => button.addEventListener("click", () => seek(Number(button.dataset.playerSeek))));
    root.querySelectorAll("[data-player-skip]").forEach((button) => button.addEventListener("click", () => { const marker = config[button.dataset.playerSkip]; if (marker) video.currentTime = marker.end; }));
    progress.addEventListener("input", () => { video.currentTime = Number(progress.value); });
    speed.addEventListener("change", () => { video.playbackRate = Number(speed.value); });
    quality.addEventListener("change", setAdaptiveQuality);
    subtitles.addEventListener("change", () => selectSubtitle(subtitles.value));
    root.querySelector("[data-player-pip]").addEventListener("click", async () => { if (document.pictureInPictureElement) await document.exitPictureInPicture(); else if (document.pictureInPictureEnabled) await video.requestPictureInPicture(); });
    root.querySelector("[data-player-fullscreen]").addEventListener("click", async () => { if (document.fullscreenElement) await document.exitFullscreen(); else await stage.requestFullscreen(); });
    root.querySelector("[data-player-cancel-next]").addEventListener("click", stopNextCountdown);
    video.addEventListener("loadedmetadata", () => { if (!resumed && config.resumeAt > 0 && config.resumeAt < video.duration - 15) video.currentTime = config.resumeAt; resumed = true; speed.value = String(config.defaultSpeed); video.playbackRate = Number(config.defaultSpeed); selectSubtitle(subtitles.value); updateTimeline(); });
    video.addEventListener("play", () => { stopNextCountdown(); setPlayButtons(); });
    video.addEventListener("pause", () => { setPlayButtons(); saveProgress(); });
    video.addEventListener("timeupdate", () => { updateTimeline(); saveProgress(); });
    video.addEventListener("ended", () => { saveProgress(true); startNextCountdown(); });
    video.addEventListener("waiting", () => setStatus("Буферизация…"));
    video.addEventListener("playing", () => setStatus(""));
    video.addEventListener("error", () => setStatus("Не удалось воспроизвести видео. Проверьте доступ к лицензированному источнику."));
    document.addEventListener("visibilitychange", () => { if (document.hidden) saveProgress(); });
    window.addEventListener("pagehide", () => saveProgress());
    document.addEventListener("keydown", (event) => {
        if (event.target.matches("input, select, textarea") || event.target.isContentEditable) return;
        if (event.code === "Space") { event.preventDefault(); video.paused ? video.play() : video.pause(); }
        else if (event.key === "ArrowLeft") seek(-10); else if (event.key === "ArrowRight") seek(10);
        else if (event.key.toLowerCase() === "m") video.muted = !video.muted;
        else if (event.key.toLowerCase() === "f") document.fullscreenElement ? document.exitFullscreen() : stage.requestFullscreen();
        else if (event.key.toLowerCase() === "p" && document.pictureInPictureEnabled) document.pictureInPictureElement ? document.exitPictureInPicture() : video.requestPictureInPicture();
    });
    setQualityOptions(); setSubtitleOptions(); attachSource(); setPlayButtons();
})();

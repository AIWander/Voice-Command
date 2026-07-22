(() => {
  "use strict";

  const state = document.getElementById("voice-state");
  const title = document.getElementById("state-title");
  const detail = document.getElementById("state-detail");
  const time = document.getElementById("playback-time");
  const progress = document.getElementById("progress-bar");
  const pauseButton = document.getElementById("pause-control");
  const transcript = document.getElementById("demo-transcript");
  const phraseInput = document.getElementById("wake-phrase");
  const simulateButton = document.getElementById("simulate-interruption");
  const cueButton = document.getElementById("play-cue");
  const copyButton = document.getElementById("copy-prompt");
  const promptText = document.getElementById("install-prompt");

  let paused = false;
  let simulationTimer = [];

  function setState(kind, heading, message, timestamp, width) {
    state.dataset.state = kind;
    title.textContent = heading;
    detail.textContent = message;
    time.textContent = timestamp;
    progress.style.width = width;
  }

  function clearSimulation() {
    simulationTimer.forEach(window.clearTimeout);
    simulationTimer = [];
    simulateButton.disabled = false;
  }

  function playTurnCue() {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) {
      cueButton.textContent = "Audio cue unavailable";
      return;
    }
    const audio = new AudioContext();
    const now = audio.currentTime + 0.04;
    const duration = 0.15;
    const gap = 0.08;

    for (let index = 0; index < 3; index += 1) {
      const start = now + index * (duration + gap);
      const oscillator = audio.createOscillator();
      const gain = audio.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.12, start + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      oscillator.connect(gain).connect(audio.destination);
      oscillator.start(start);
      oscillator.stop(start + duration + 0.02);
    }

    window.setTimeout(() => audio.close(), 1100);
  }

  document.querySelectorAll("[data-control]").forEach((button) => {
    button.addEventListener("click", () => {
      clearSimulation();
      const action = button.dataset.control;

      if (action === "pause") {
        paused = !paused;
        pauseButton.textContent = paused ? "Resume" : "Pause";
        if (paused) {
          setState("paused", "Paused", "Playback held · phrase listener still armed", "00:18 / 00:42", "43%");
        } else {
          setState("speaking", "Speaking", "Silent interruption listener armed", "00:18 / 00:42", "43%");
        }
      }

      if (action === "interrupt") {
        paused = false;
        pauseButton.textContent = "Pause";
        setState("listening", "Your turn", "Regular listener open after triple-beep cue", "LISTENING", "100%");
        transcript.innerHTML = '<p><span>AI</span> Unheard audio was skipped.</p><p class="user-line"><span>YOU</span> Listening for your new direction…</p>';
        playTurnCue();
      }

      if (action === "stop") {
        paused = false;
        pauseButton.textContent = "Pause";
        setState("stopped", "Stopped", "Exchange ended · microphone closed", "OFF", "0%");
        transcript.innerHTML = '<p><span>VOICE</span> Session stopped by the user.</p>';
      }
    });
  });

  cueButton.addEventListener("click", playTurnCue);

  simulateButton.addEventListener("click", () => {
    clearSimulation();
    simulateButton.disabled = true;
    const phrase = phraseInput.value.trim() || "umm";
    transcript.innerHTML = `<p><span>AI</span> I can compare those options and then walk you through the strongest one—</p><p class="user-line"><span>YOU</span> “${phrase}” detected silently</p>`;
    setState("paused", "Phrase heard", `Paused at the current position · handing off`, "00:18 / 00:42", "43%");

    simulationTimer.push(window.setTimeout(() => {
      setState("listening", "Your turn", "Triple-beep cue · full transcription listener open", "LISTENING", "43%");
      playTurnCue();
    }, 650));

    simulationTimer.push(window.setTimeout(() => {
      transcript.innerHTML += '<p class="user-line"><span>YOU</span> Actually, only compare the options that work offline.</p>';
      setState("speaking", "Revising response", "New input plus prior answer context returned to the AI", "THINKING", "43%");
    }, 1750));

    simulationTimer.push(window.setTimeout(() => {
      transcript.innerHTML += '<p><span>AI</span> That narrows it to two. Here is the faster offline option first…</p>';
      setState("speaking", "Speaking", "Revised answer · silent interruption listener re-armed", "00:03 / 00:26", "12%");
      simulateButton.disabled = false;
      simulationTimer = [];
    }, 2900));
  });

  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(promptText.textContent.trim());
      copyButton.textContent = "Copied";
      window.setTimeout(() => { copyButton.textContent = "Copy"; }, 1800);
    } catch (_error) {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(promptText);
      selection.removeAllRanges();
      selection.addRange(range);
      copyButton.textContent = "Selected";
    }
  });
})();

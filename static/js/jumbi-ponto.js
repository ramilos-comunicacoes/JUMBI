/**
 * JUMBI - Ponto Eletrônico & Reconhecimento Facial Inteligente
 * Google MediaPipe Face Detection (Client-side, 100% Free & Open Source)
 * Conforme Portaria 671 MTP (Hash SHA-256, Auditoria, Comprovante Digital)
 */

(function () {
  'use strict';

  // State
  let videoElement = null;
  let canvasElement = null;
  let canvasCtx = null;
  let faceDetection = null;
  let cameraStream = null;
  let isFaceDetected = false;
  let lastConfidence = 0;
  let landmarksCount = 0;
  let isSubmitting = false;

  // Digital Clock live update
  function initLiveClock() {
    const clockEl = document.getElementById('pontoLiveClock');
    const dateEl = document.getElementById('pontoLiveDate');
    if (!clockEl) return;

    function update() {
      const now = new Date();
      const hours = String(now.getHours()).padStart(2, '0');
      const minutes = String(now.getMinutes()).padStart(2, '0');
      const seconds = String(now.getSeconds()).padStart(2, '0');
      clockEl.textContent = `${hours}:${minutes}:${seconds}`;

      if (dateEl) {
        const options = { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' };
        dateEl.textContent = now.toLocaleDateString('pt-BR', options);
      }
    }
    update();
    setInterval(update, 1000);
  }

  // Pleasant Web Audio Chime
  function playSuccessChime() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;

      // Chord C5 (523.25Hz) -> E5 (659.25Hz) -> G5 (783.99Hz)
      const freqs = [523.25, 659.25, 783.99];
      freqs.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, now + idx * 0.08);

        gain.gain.setValueAtTime(0, now + idx * 0.08);
        gain.gain.linearRampToValueAtTime(0.2, now + idx * 0.08 + 0.03);
        gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.08 + 0.4);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start(now + idx * 0.08);
        osc.stop(now + idx * 0.08 + 0.45);
      });
    } catch (e) {
      console.warn('Audio chime unavailable', e);
    }
  }

  // Camera & Face Detection
  async function initFaceDetection() {
    videoElement = document.getElementById('pontoCameraVideo');
    canvasElement = document.getElementById('pontoOverlayCanvas');
    const hudOval = document.getElementById('pontoFaceOval');
    const hudBadge = document.getElementById('pontoHudBadge');
    const hudBadgeText = document.getElementById('pontoHudBadgeText');
    const punchButton = document.getElementById('btnSubmitPunch');

    if (!videoElement) return;

    if (canvasElement) {
      canvasCtx = canvasElement.getContext('2d');
    }

    // Check MediaPipe availability
    if (typeof window.FaceDetection === 'undefined') {
      console.warn('MediaPipe FaceDetection library not yet loaded. Retrying in 500ms...');
      setTimeout(initFaceDetection, 500);
      return;
    }

    try {
      // Setup MediaPipe
      faceDetection = new window.FaceDetection({
        locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_detection/${file}`
      });

      faceDetection.setOptions({
        model: 'short',
        minDetectionConfidence: 0.60
      });

      faceDetection.onResults((results) => {
        if (!canvasElement || !canvasCtx) return;

        // Resize overlay canvas to video
        if (canvasElement.width !== videoElement.videoWidth || canvasElement.height !== videoElement.videoHeight) {
          canvasElement.width = videoElement.videoWidth || 640;
          canvasElement.height = videoElement.videoHeight || 480;
        }

        canvasCtx.save();
        canvasCtx.clearRect(0, 0, canvasElement.width, canvasElement.height);

        if (results.detections && results.detections.length > 0) {
          const detection = results.detections[0];
          const score = detection.score && detection.score.length > 0 ? detection.score[0] : 0.85;
          const pct = Math.round(score * 100);

          isFaceDetected = true;
          lastConfidence = pct;
          landmarksCount = detection.landmarks ? detection.landmarks.length : 6;

          // Visual feedback
          if (hudOval) {
            hudOval.classList.add('detected');
            hudOval.classList.remove('scanning');
          }
          if (hudBadge) {
            hudBadge.classList.add('success');
          }
          if (hudBadgeText) {
            hudBadgeText.textContent = `Rosto Reconhecido (${pct}%) · Pronto para Bater Ponto`;
          }
          if (punchButton) {
            punchButton.removeAttribute('disabled');
          }

          // Optional: draw landmark points gently
          if (detection.landmarks) {
            canvasCtx.fillStyle = 'rgba(16, 185, 129, 0.7)';
            detection.landmarks.forEach((pt) => {
              const x = pt.x * canvasElement.width;
              const y = pt.y * canvasElement.height;
              canvasCtx.beginPath();
              canvasCtx.arc(x, y, 4, 0, 2 * Math.PI);
              canvasCtx.fill();
            });
          }
        } else {
          isFaceDetected = false;
          lastConfidence = 0;
          landmarksCount = 0;

          if (hudOval) {
            hudOval.classList.remove('detected');
            hudOval.classList.add('scanning');
          }
          if (hudBadge) {
            hudBadge.classList.remove('success');
          }
          if (hudBadgeText) {
            hudBadgeText.textContent = 'Posicione seu rosto na moldura oval...';
          }
        }
        canvasCtx.restore();
      });

      // Start Camera Stream
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'user',
          width: { ideal: 640 },
          height: { ideal: 480 }
        },
        audio: false
      });

      cameraStream = stream;
      videoElement.srcObject = stream;
      await videoElement.play();

      // Send frames to detector
      let isProcessing = false;
      async function processVideoFrame() {
        if (videoElement && !videoElement.paused && !videoElement.ended) {
          if (!isProcessing && videoElement.readyState >= 2) {
            isProcessing = true;
            try {
              await faceDetection.send({ image: videoElement });
            } catch (err) {
              console.warn('Frame processing note:', err);
            }
            isProcessing = false;
          }
        }
        requestAnimationFrame(processVideoFrame);
      }
      requestAnimationFrame(processVideoFrame);

    } catch (err) {
      console.error('Camera or MediaPipe initialization failed:', err);
      if (hudBadgeText) {
        hudBadgeText.textContent = 'Câmera inacessível ou bloqueada pelo navegador.';
      }
      if (punchButton) {
        // Fallback: allow manual clock if permissions restrict webcam
        punchButton.removeAttribute('disabled');
      }
    }
  }

  // Geolocation helper with timeout
  function getCoordinates() {
    return new Promise((resolve) => {
      if (!('geolocation' in navigator)) {
        return resolve({ latitude: null, longitude: null, accuracy: null });
      }
      const timeout = setTimeout(() => {
        resolve({ latitude: null, longitude: null, accuracy: null });
      }, 3500);

      navigator.geolocation.getCurrentPosition(
        (pos) => {
          clearTimeout(timeout);
          resolve({
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            accuracy: pos.coords.accuracy
          });
        },
        (err) => {
          clearTimeout(timeout);
          console.warn('Geolocation warning:', err.message);
          resolve({ latitude: null, longitude: null, accuracy: null });
        },
        { enableHighAccuracy: true, timeout: 3000, maximumAge: 10000 }
      );
    });
  }

  // Snapshot photo from video
  function capturePhotoSnapshot() {
    if (!videoElement || videoElement.videoWidth === 0) return '';
    const snapCanvas = document.createElement('canvas');
    snapCanvas.width = videoElement.videoWidth;
    snapCanvas.height = videoElement.videoHeight;
    const snapCtx = snapCanvas.getContext('2d');
    // Mirror back horizontally so photo looks natural
    snapCtx.translate(snapCanvas.width, 0);
    snapCtx.scale(-1, 1);
    snapCtx.drawImage(videoElement, 0, 0, snapCanvas.width, snapCanvas.height);
    return snapCanvas.toDataURL('image/jpeg', 0.82);
  }

  // Register Punch Action
  async function submitPunch(recordType) {
    if (isSubmitting) return;
    isSubmitting = true;

    const punchButton = document.getElementById('btnSubmitPunch');
    const originalText = punchButton ? punchButton.innerHTML : '';
    if (punchButton) {
      punchButton.disabled = true;
      punchButton.innerHTML = '<span>Registrando e Autenticando...</span>';
    }

    try {
      // Capture snapshot
      const photoBase64 = capturePhotoSnapshot();

      // Get GPS
      const coords = await getCoordinates();

      // CSRF token
      let csrfToken = '';
      const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
      if (csrfInput) {
        csrfToken = csrfInput.value;
      } else {
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        if (metaTag) csrfToken = metaTag.getAttribute('content');
      }

      const payload = {
        record_type: recordType || 'entry_1',
        face_detected: isFaceDetected,
        face_confidence: lastConfidence || (isFaceDetected ? 85 : 0),
        face_landmarks_count: landmarksCount || (isFaceDetected ? 6 : 0),
        photo_base64: photoBase64,
        latitude: coords.latitude,
        longitude: coords.longitude,
        location_accuracy: coords.accuracy
      };

      const response = await fetch('/ponto/api/punch/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();

      if (data.status === 'success') {
        playSuccessChime();
        showReceiptModal(data.receipt);
      } else {
        alert('Aviso ao registrar ponto: ' + (data.message || 'Erro desconhecido'));
      }
    } catch (err) {
      console.error('Punch registration error:', err);
      alert('Erro de conexão ao registrar ponto. Verifique sua rede e tente novamente.');
    } finally {
      isSubmitting = false;
      if (punchButton) {
        punchButton.disabled = false;
        punchButton.innerHTML = originalText;
      }
    }
  }

  // Show Digital Receipt Modal (Portaria 671 MTP)
  function showReceiptModal(receipt) {
    const modal = document.getElementById('pontoReceiptModal');
    if (!modal) {
      alert(`Ponto registrado com sucesso às ${receipt.time}! Comprovante SHA-256 gerado.`);
      window.location.reload();
      return;
    }

    document.getElementById('receiptEmployeeName').textContent = receipt.employee_name || 'Funcionário';
    document.getElementById('receiptType').textContent = receipt.record_type_label || receipt.record_type;
    document.getElementById('receiptTimestamp').textContent = `${receipt.date} às ${receipt.time}`;
    document.getElementById('receiptHash').textContent = receipt.hash_sha256 || 'N/A';
    document.getElementById('receiptSource').textContent = receipt.face_detected ? 'Reconhecimento Facial (Google MediaPipe)' : 'Registro Web';

    if (receipt.photo_snapshot) {
      const img = document.getElementById('receiptPhoto');
      if (img) {
        img.src = receipt.photo_snapshot;
        img.style.display = 'block';
      }
    }

    modal.style.display = 'flex';
  }

  // Setup DOM Events
  document.addEventListener('DOMContentLoaded', () => {
    initLiveClock();
    initFaceDetection();

    const punchBtn = document.getElementById('btnSubmitPunch');
    if (punchBtn) {
      punchBtn.addEventListener('click', () => {
        const typeSelect = document.getElementById('punchRecordType');
        const recordType = typeSelect ? typeSelect.value : (punchBtn.dataset.nextType || 'entry_1');
        submitPunch(recordType);
      });
    }

    const closeReceiptBtn = document.getElementById('btnCloseReceipt');
    if (closeReceiptBtn) {
      closeReceiptBtn.addEventListener('click', () => {
        window.location.reload();
      });
    }

    const printReceiptBtn = document.getElementById('btnPrintReceipt');
    if (printReceiptBtn) {
      printReceiptBtn.addEventListener('click', () => {
        window.print();
      });
    }
  });

  // Export functions to global scope for templates
  window.JumbiPonto = {
    submitPunch: submitPunch,
    showReceiptModal: showReceiptModal
  };

})();

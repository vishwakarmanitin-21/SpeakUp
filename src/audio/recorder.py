from __future__ import annotations

import io

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as wav_write


class AudioRecorder:
    """Records audio from the chosen (or default) microphone using push-to-talk.

    Uses sounddevice.InputStream with a callback so recording length
    is not predetermined. Audio is kept entirely in memory — no files
    are written to disk.
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._is_recording = False
        self._on_silence: callable | None = None

    def set_silence_callback(self, callback: callable) -> None:
        """Set a callback that fires when silence is detected.

        The callback receives the current audio frame (np.ndarray).
        Used by SilenceDetector integration.
        """
        self._on_silence = callback

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """Called by sounddevice for each audio chunk."""
        if self._is_recording:
            self._frames.append(indata.copy())

    def start(self) -> None:
        """Begin recording from the default input device.

        Raises:
            RecordingError: If the microphone cannot be opened.
        """
        from src.services.error_handler import RecordingError

        self._frames = []
        self._is_recording = True
        try:
            from src.audio.devices import resolve_input_device

            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="float32",
                device=resolve_input_device(),  # the mic chosen in Settings
                callback=self._audio_callback,
            )
            self._stream.start()
        except sd.PortAudioError as e:
            self._is_recording = False
            raise RecordingError(
                f"Failed to open microphone: {e}",
                "Could not access the microphone. Check that it is connected and not in use by another application.",
            ) from e

    def stop(self) -> None:
        """Stop recording and close the audio stream."""
        self._is_recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def get_wav_bytes(self) -> io.BytesIO:
        """Return recorded audio as an in-memory WAV file.

        Returns a BytesIO object with a .name attribute set to
        "recording.wav" (required by the OpenAI client).

        Raises:
            ValueError: If no audio has been recorded.
        """
        if not self._frames:
            raise ValueError("No audio recorded")

        audio_data = np.concatenate(self._frames, axis=0)
        # Convert float32 [-1, 1] to int16 for WAV format
        audio_int16 = (audio_data * 32767).astype(np.int16)

        buffer = io.BytesIO()
        wav_write(buffer, self._sample_rate, audio_int16)
        buffer.seek(0)
        buffer.name = "recording.wav"
        return buffer

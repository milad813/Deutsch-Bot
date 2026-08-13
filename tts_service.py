"""TTS service using edge-tts."""

import hashlib
import logging
import os
import tempfile
import time

import config

logger = logging.getLogger(__name__)

try:
    import edge_tts

    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts نصب نشده است. قابلیت تلفظ غیرفعال است.")


class TTSService:
    """Text-to-speech service with caching and cleanup."""

    MAX_CACHE_SIZE_MB = 100
    MAX_CACHE_AGE_DAYS = 7

    def __init__(self):
        self.cache_dir = config.AUDIO_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    async def get_audio_path(self, text: str, voice: str = "de-DE-KatjaNeural") -> str:
        if not EDGE_TTS_AVAILABLE:
            return None

        clean_text = text.strip()
        if not clean_text:
            return None

        filename = hashlib.md5(clean_text.encode("utf-8")).hexdigest() + ".mp3"
        filepath = os.path.join(self.cache_dir, filename)

        if os.path.exists(filepath):
            return filepath

        tmp_fd = None
        tmp_path = None

        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=self.cache_dir, suffix=".mp3")
            os.close(tmp_fd)
            tmp_fd = None

            communicate = edge_tts.Communicate(clean_text, voice=voice)
            await communicate.save(tmp_path)

            os.replace(tmp_path, filepath)
            tmp_path = None
        except Exception as e:
            logger.error("خطا در تولید صدا برای '%s': %s", text, e)

            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            return None
        finally:
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except Exception:
                    pass

        return filepath

    def cleanup_cache(self):
        """Remove old or oversized cache files."""
        if not os.path.exists(self.cache_dir):
            return

        files = []
        for f in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, f)
            if os.path.isfile(path) and f.endswith(".mp3"):
                files.append((path, os.path.getmtime(path), os.path.getsize(path)))

        # Remove old files
        cutoff = time.time() - (self.MAX_CACHE_AGE_DAYS * 86400)
        for path, mtime, size in files:
            if mtime < cutoff:
                try:
                    os.unlink(path)
                    logger.info("TTS cache cleanup: %s", path)
                except Exception as e:
                    logger.warning("Failed to delete %s: %s", path, e)

        # If still too large, remove oldest first
        files = [(p, m, s) for p, m, s in files if os.path.exists(p)]
        total_size = sum(s for _, _, s in files)
        max_bytes = self.MAX_CACHE_SIZE_MB * 1024 * 1024

        if total_size > max_bytes:
            files.sort(key=lambda x: x[1])  # Oldest first
            while total_size > max_bytes and files:
                path, _, size = files.pop(0)
                if os.path.exists(path):
                    try:
                        os.unlink(path)
                        total_size -= size
                        logger.info("TTS cache size cleanup: %s", path)
                    except Exception as e:
                        logger.warning("Failed to delete %s: %s", path, e)

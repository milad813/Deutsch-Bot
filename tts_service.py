import os
import logging
import hashlib
import tempfile

import config

logger = logging.getLogger(__name__)

try:
    import edge_tts

    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts نصب نشده است. قابلیت تلفظ غیرفعال است.")


class TTSService:
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

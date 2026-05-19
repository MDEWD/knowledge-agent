import os
import tempfile
import yt_dlp

_model = None

_PUNCT_CHUNK = 1500  # chars per DeepSeek call to stay well within token limits


def _load_model():
    global _model
    if _model is None:
        import whisper
        from config import WHISPER_MODEL
        _model = whisper.load_model(WHISPER_MODEL, device="cpu")
    return _model


def _restore_punctuation(text: str) -> str:
    """Use DeepSeek to add punctuation to raw Whisper output."""
    from openai import OpenAI
    from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    # Process in chunks so long transcripts don't exceed token limits
    chunks = [text[i:i + _PUNCT_CHUNK] for i in range(0, len(text), _PUNCT_CHUNK)]
    result_parts = []
    for chunk in chunks:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=2048,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个文本标点还原专家。"
                        "用户会给你一段没有标点的语音识别文本，"
                        "请帮它加上合适的中文标点符号（逗号、句号、问号、感叹号等），"
                        "适当分段，保持原文内容完全不变，只添加标点和换行，不要任何解释。"
                    ),
                },
                {"role": "user", "content": chunk},
            ],
        )
        result_parts.append(resp.choices[0].message.content or chunk)

    return "\n\n".join(result_parts)


def transcribe(url: str) -> str:
    model = _load_model()

    with tempfile.TemporaryDirectory() as tmpdir:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{tmpdir}/audio.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "legacy_server_connect": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        audio_files = [f for f in os.listdir(tmpdir)]
        if not audio_files:
            raise RuntimeError("No audio file downloaded")

        audio_path = os.path.join(tmpdir, audio_files[0])
        result = model.transcribe(audio_path, fp16=False, language="zh")
        raw_text = result["text"]

    return _restore_punctuation(raw_text)


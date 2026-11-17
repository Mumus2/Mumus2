"""Download (yt-dlp) e edição (ffmpeg) dos clipes."""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from .config import Config
from .db import DB, DOWNLOADED, FAILED, RENDERED

log = logging.getLogger(__name__)


def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def ytdlp_cmd(url: str, out: Path, start: float | None = None, end: float | None = None) -> list[str]:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-progress", "--no-playlist", "--force-overwrites",
        "-f", "best[height<=1080]/best",
        "-o", str(out),
    ]
    if start is not None and end is not None:
        cmd += ["--download-sections", f"*{fmt_ts(start)}-{fmt_ts(end)}", "--force-keyframes-at-cuts"]
    return cmd + [url]


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _drawtext(textfile: Path, font: str, size: int, y: str, x: str = "(w-tw)/2", border: int = 4) -> str:
    # textfile= evita todo o inferno de escapar acentos, ':' e aspas no drawtext
    return (
        f"drawtext=fontfile='{font}':textfile='{textfile}':fontsize={size}:fontcolor=white:"
        f"borderw={border}:bordercolor=black@0.85:x={x}:y={y}"
    )


def vertical_filter(name_file: Path, handle_file: Path, mark_file: Path | None, font: str) -> str:
    """9:16 (Shorts): fundo desfocado + vídeo original centralizado + créditos."""
    parts = [
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=28,eq=brightness=-0.10[bg]",
        "[0:v]scale=1080:-2[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        # posições fogem da área coberta pela interface do Shorts (rodapé e lateral direita)
        + _drawtext(name_file, font, 70, "h*0.20")
        + ","
        + _drawtext(handle_file, font, 42, "h*0.685", border=3)
        + ("," + _drawtext(mark_file, font, 32, "h*0.12", border=2) if mark_file else "")
        + ",fps=30,format=yuv420p[v]",
    ]
    return ";".join(parts)


def horizontal_filter(name_file: Path, mark_file: Path | None, font: str) -> str:
    """16:9: vídeo com faixas pretas se preciso + nome do streamer no canto."""
    chain = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        + _drawtext(name_file, font, 48, "40", x="40", border=3)
        + ("," + _drawtext(mark_file, font, 32, "h-70", x="w-tw-40", border=2) if mark_file else "")
        + ",fps=30,format=yuv420p[v]"
    )
    return chain


def ffmpeg_cmd(src: Path, dst: Path, vfilter: str, crf: int, preset: str) -> list[str]:
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-filter_complex", vfilter,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]


def run(cmd: list[str], timeout: int = 1800) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "erro desconhecido")[-1500:])


class MediaWorker:
    def __init__(self, cfg: Config, db: DB):
        self.cfg = cfg
        self.db = db
        self.rcfg = cfg["render"]

    def clip_dir(self, clip) -> Path:
        d = self.cfg.videos_dir / clip["login"] / str(clip["id"])
        d.mkdir(parents=True, exist_ok=True)
        return d

    def download(self, clip) -> Path:
        d = self.clip_dir(clip)
        out = d / "raw.mp4"
        if clip["source"] == "hype":
            cmd = ytdlp_cmd(clip["url"], out, clip["start_s"], clip["end_s"])
        else:
            cmd = ytdlp_cmd(clip["url"], out)
        run(cmd)
        if not out.exists():  # yt-dlp às vezes troca a extensão
            found = sorted(d.glob("raw.*"))
            if not found:
                raise RuntimeError("yt-dlp terminou sem gerar arquivo")
            out = found[0]
        self.db.update_clip(clip["id"], raw_path=str(out), status=DOWNLOADED, error=None)
        return out

    def render(self, clip, raw: Path) -> None:
        d = self.clip_dir(clip)
        streamer = self.db.one("SELECT display_name FROM streamers WHERE login=?", (clip["login"],))
        name = (streamer["display_name"] if streamer and streamer["display_name"] else clip["login"])
        font = self.rcfg["font_file"]
        name_f = _write_text(d / "name.txt", name)
        handle_f = _write_text(d / "handle.txt", f"twitch.tv/{clip['login']}")
        mark = self.rcfg.get("watermark") or ""
        mark_f = _write_text(d / "mark.txt", mark) if mark else None
        fields = {}
        if self.rcfg.get("vertical", True):
            dst = d / "vertical.mp4"
            run(ffmpeg_cmd(raw, dst, vertical_filter(name_f, handle_f, mark_f, font), self.rcfg["crf"], self.rcfg["preset"]))
            fields["vertical_path"] = str(dst)
        if self.rcfg.get("horizontal", False):
            dst = d / "horizontal.mp4"
            run(ffmpeg_cmd(raw, dst, horizontal_filter(name_f, mark_f, font), self.rcfg["crf"], self.rcfg["preset"]))
            fields["horizontal_path"] = str(dst)
        self.db.update_clip(clip["id"], status=RENDERED, error=None, **fields)

    def render_horizontal_for_compilation(self, clip) -> Path:
        d = self.clip_dir(clip)
        dst = d / "horizontal.mp4"
        if dst.exists():
            return dst
        streamer = self.db.one("SELECT display_name FROM streamers WHERE login=?", (clip["login"],))
        name = streamer["display_name"] if streamer and streamer["display_name"] else clip["login"]
        name_f = _write_text(d / "name_h.txt", f"{name} • twitch.tv/{clip['login']}")
        mark = self.rcfg.get("watermark") or ""
        mark_f = _write_text(d / "mark.txt", mark) if mark else None
        run(ffmpeg_cmd(Path(clip["raw_path"]), dst, horizontal_filter(name_f, mark_f, self.rcfg["font_file"]),
                       self.rcfg["crf"], self.rcfg["preset"]))
        self.db.update_clip(clip["id"], horizontal_path=str(dst))
        return dst

    def build_compilation(self, clips: list, out: Path) -> Path:
        parts = [self.render_horizontal_for_compilation(c) for c in clips]
        listing = out.with_suffix(".txt")
        listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)])
        return out

    def process_pending(self, per_streamer: int = 6) -> int:
        """Baixa e edita os melhores candidatos de cada streamer."""
        rows = self.db.query(
            "SELECT * FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY login ORDER BY score DESC) rn "
            "FROM clips c WHERE status IN ('candidate','downloaded') AND (approved IS NULL OR approved=1)) "
            "WHERE rn <= ? ORDER BY score DESC",
            (per_streamer,),
        )
        done = 0
        for clip in rows:
            try:
                raw = Path(clip["raw_path"]) if clip["raw_path"] else self.download(clip)
                self.render(clip, raw)
                done += 1
                log.info("Clipe pronto: #%s %s", clip["id"], clip["login"])
            except Exception as e:
                log.error("Falha no clipe #%s (%s): %s", clip["id"], clip["login"], e)
                self.db.update_clip(clip["id"], status=FAILED, error=str(e)[-1000:])
        return done

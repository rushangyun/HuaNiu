/**
 * 有声书创作面板。
 *
 * 纯展示 + 简单交互：把 useAudiobook 产出的状态画出来，
 * 用户操作（粘贴/上传/选音色/合成/试听）都回调给 hook，
 * 不在这里直接发请求。
 */

import { useState } from "react";
import { useAudiobook } from "../hooks/useAudiobook";
import {
  chapterAudioUrl,
  downloadUrl,
  segmentAudioUrl,
  VOICES,
} from "../api/audiobook";

const STATUS_TEXT: Record<string, string> = {
  parsing: "解析中…",
  parsed: "解析完成 · 可配置音色",
  synthesizing: "合成中…",
  done: "已完成",
  failed: "失败",
};

export function AudiobookView() {
  const ab = useAudiobook();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [ack, setAck] = useState(false);
  const [showSegs, setShowSegs] = useState(false);

  const d = ab.detail;
  const progressPct = ab.progress?.pct ?? d?.progress.pct ?? 0;
  const progressMsg =
    ab.progress?.message || (d ? STATUS_TEXT[d.status] || d.status : "");

  const canCreate = ack && text.trim().length > 0 && !ab.busy;
  const canSynth =
    !!d &&
    (d.status === "parsed" ||
      d.status === "failed" ||
      d.status === "synthesizing" ||
      d.status === "done") &&
    !ab.busy;

  return (
    <div className="ab">
      <div className="ab-grid">
        {/* 左：创作台 */}
        <section className="ab-card">
          <h3>创作台</h3>
          <input
            className="ab-input"
            placeholder="书名（可选）"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className="ab-textarea"
            placeholder="把小说正文粘贴到这里（支持「第X章」自动分章）。请确保你对文本拥有合法使用权。"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="ab-row">
            <label className="ab-ack">
              <input
                type="checkbox"
                checked={ack}
                onChange={(e) => setAck(e.target.checked)}
              />
              我确认拥有该文本的合法使用权
            </label>
          </div>
          <div className="ab-row">
            <button
              className="ab-btn"
              disabled={!canCreate}
              onClick={() => ab.create(title.trim() || "未命名", text)}
            >
              生成有声书
            </button>
            <span className="ab-hint">解析约几秒～十几秒</span>
          </div>
          <div className="ab-row">
            <span className="ab-hint">或上传文件：</span>
            <input
              type="file"
              accept=".txt,.md"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) ab.upload(f);
              }}
            />
          </div>
        </section>

        {/* 右：我的有声书 */}
        <section className="ab-card">
          <h3>我的有声书</h3>
          {ab.novels.length === 0 ? (
            <div className="ab-empty">还没有书，先在左边生成一本。</div>
          ) : (
            <ul className="ab-list">
              {ab.novels.map((n) => (
                <li
                  key={n.id}
                  className={d?.id === n.id ? "active" : ""}
                  onClick={() => ab.open(n.id)}
                >
                  <span className="ab-list-title">{n.title}</span>
                  <span className={`ab-badge ${n.status}`}>
                    {STATUS_TEXT[n.status] || n.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* 制作面板 */}
      {d && (
        <section className="ab-card ab-make">
          <div className="ab-row ab-make-head">
            <h3>{d.title}</h3>
            <span className={`ab-badge ${d.status}`}>
              {STATUS_TEXT[d.status] || d.status}
            </span>
          </div>

          {(d.status === "parsing" ||
            ab.progress?.phase === "parsing" ||
            d.status === "synthesizing") && (
            <div className="ab-progress">
              <div className="ab-bar">
                <div
                  className="ab-bar-fill"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <span className="ab-progress-msg">{progressMsg}</span>
            </div>
          )}

          {/* 角色音色配置 */}
          {d.speakers.length > 0 && (
            <div className="ab-block">
              <h4>角色音色</h4>
              {d.speakers.map((sp) => (
                <div className="ab-speaker" key={sp.name}>
                  <span className="ab-speaker-name">{sp.name}</span>
                  <select
                    className="ab-input"
                    value={sp.voice_id || ""}
                    onChange={(e) =>
                      ab.saveSpeaker(sp.name, {
                        voice_id: e.target.value || null,
                      })
                    }
                  >
                    <option value="">（默认·旁白音色）</option>
                    {VOICES.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                  <label className="ab-speed">
                    语速
                    <input
                      type="number"
                      step="0.05"
                      min="0.5"
                      max="2"
                      className="ab-input ab-input-sm"
                      value={sp.speed ?? 1}
                      onChange={(e) =>
                        ab.saveSpeaker(sp.name, {
                          speed: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                </div>
              ))}
            </div>
          )}

          {/* 合成按钮 + 下载 */}
          <div className="ab-row">
            <button
              className="ab-btn"
              disabled={!canSynth}
              onClick={() => ab.startSynthesis()}
            >
              {d.status === "done" ? "重新合成" : "开始合成"}
            </button>
            {d.status === "done" && (
              <>
                <a className="ab-btn ghost" href={downloadUrl(d.id, "book")}>
                  下载全书
                </a>
                <a className="ab-btn ghost" href={downloadUrl(d.id, "zip")}>
                  下载全部章节(zip)
                </a>
              </>
            )}
          </div>

          {/* 章节播放器 */}
          {d.chapters.length > 0 && (
            <div className="ab-block">
              <h4>章节</h4>
              {d.chapters.map((c) => {
                const hasAudio = c.status === "done";
                return (
                  <div className="ab-chapter" key={c.id}>
                    <div className="ab-chapter-head">
                      <span>
                        第{c.idx + 1}章 · {c.title}
                      </span>
                      {c.duration_sec != null && (
                        <span className="ab-hint">
                          {Math.round(c.duration_sec)}s
                        </span>
                      )}
                      {hasAudio && (
                        <a
                          className="ab-link"
                          href={downloadUrl(d.id, "chapter", c.idx)}
                        >
                          下载
                        </a>
                      )}
                    </div>
                    {hasAudio ? (
                      <audio
                        className="ab-audio"
                        controls
                        src={chapterAudioUrl(d.id, c.idx)}
                      />
                    ) : (
                      <span className="ab-hint">
                        {c.status === "done" ? "音频生成中…" : "待合成"}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* 段落试听（折叠） */}
          <div className="ab-block">
            <button
              className="ab-link"
              onClick={() => setShowSegs((v) => !v)}
            >
              {showSegs ? "收起段落" : `查看段落（${d.progress.total}）`}
            </button>
            {showSegs && (
              <div className="ab-segs">
                {ab.segments.map((s) => (
                  <div className="ab-seg" key={s.id}>
                    <div className="ab-seg-meta">
                      <span className="ab-seg-speaker">
                        {s.speaker || "旁白"}
                      </span>
                      {s.kind === "dialogue" && (
                        <span className="ab-tag">对白</span>
                      )}
                      {s.kind === "narration" && (
                        <span className="ab-tag">旁白</span>
                      )}
                    </div>
                    <div className="ab-seg-text">{s.text}</div>
                    {s.status === "done" ? (
                      <audio
                        className="ab-audio-sm"
                        controls
                        src={segmentAudioUrl(d.id, s.id)}
                      />
                    ) : s.status === "failed" ? (
                      <span className="ab-err">合成失败：{s.error}</span>
                    ) : (
                      <span className="ab-hint">未合成（{s.status}）</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

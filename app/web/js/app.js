const { createApp } = Vue;

const WELCOME = [
  "你好，我是 **SecKB 企业网络安全助手**。",
  "",
  "可以聊聊漏洞分析与利用、加固建议、等保合规、应急响应这些方向，有问题直接问。",
].join("\n");

createApp({
  data() {
    const savedId = localStorage.getItem("rag_thread_id");
    const savedMsgs = savedId ? localStorage.getItem("rag_messages_" + savedId) : null;
    return {
      view: "chat",
      dark: true,
      stopRequested: false,
      streamReader: null,
      threadId: savedId || this.newThreadId(),
      draft: "",
      isStreaming: false,
      abortController: null,
      messages: savedMsgs ? JSON.parse(savedMsgs) : [{ role: "bot", content: WELCOME }],
      // 文档管理
      docs: [],
      docSearch: "",
      docSearchInput: "",
      pageSize: 10,
      page: 1,
      total: 0,
      totalPages: 0,
      dragging: false,
      uploading: false,
      uploadingFiles: [], // 上传/向量化进度
      // 认证
      token: localStorage.getItem("rag_token") || "",
      currentUser: null, // {id, username, role, ...}
      authReady: false,   // 启动时校验 token 完成
      loginForm: { username: "", password: "", error: "", loading: false },
    };
  },
  async mounted() {
    // 应用默认主题（深色）
    document.documentElement.classList.toggle("dark", this.dark);
    // 启动时校验本地 token 是否仍有效
    if (this.token) {
      try {
        const r = await this.apiFetch("/auth/me");
        if (r.ok) this.currentUser = await r.json();
        else this.logout();
      } catch (e) {
        this.logout();
      }
    }
    this.authReady = true;
    if (this.currentUser) {
      localStorage.setItem("rag_thread_id", this.threadId);
      this.loadDocuments();
    }
  },
  computed: {
    rangeStart() {
      return this.total === 0 ? 0 : (this.page - 1) * this.pageSize + 1;
    },
    rangeEnd() {
      return Math.min(this.page * this.pageSize, this.total);
    },
    isAdmin() {
      return this.currentUser && this.currentUser.role === "admin";
    },
  },
  computed: {
    rangeStart() {
      return this.total === 0 ? 0 : (this.page - 1) * this.pageSize + 1;
    },
    rangeEnd() {
      return Math.min(this.page * this.pageSize, this.total);
    },
  },
  methods: {
    newThreadId() {
      return "web-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
    },
    renderMd(text) {
      if (!text) return "";
      return marked.parse(text, { breaks: true, gfm: true });
    },
    toggleTheme() {
      this.dark = !this.dark;
      document.documentElement.classList.toggle("dark", this.dark);
    },
    // 统一封装 fetch：自动带 Authorization 头，401 自动登出跳回登录页
    async apiFetch(url, options = {}) {
      const headers = Object.assign({}, options.headers || {});
      if (this.token) headers["Authorization"] = "Bearer " + this.token;
      const r = await fetch(url, Object.assign({}, options, { headers }));
      if (r.status === 401) {
        this.logout();
        throw new Error("未授权，请重新登录");
      }
      return r;
    },
    async login() {
      this.loginForm.error = "";
      const u = this.loginForm.username.trim();
      const p = this.loginForm.password;
      if (!u || !p) {
        this.loginForm.error = "用户名和密码不能为空";
        return;
      }
      this.loginForm.loading = true;
      try {
        const r = await fetch("/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: u, password: p }),
        });
        const data = await r.json();
        if (!r.ok) {
          this.loginForm.error = data.detail || "登录失败";
          return;
        }
        this.token = data.access_token;
        this.currentUser = data.user;
        localStorage.setItem("rag_token", this.token);
        localStorage.setItem("rag_thread_id", this.threadId);
        this.loginForm.password = "";
        this.loadDocuments();
      } catch (e) {
        this.loginForm.error = "网络错误：" + e.message;
      } finally {
        this.loginForm.loading = false;
      }
    },
    logout() {
      this.token = "";
      this.currentUser = null;
      localStorage.removeItem("rag_token");
    },
    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.messages;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
    autoGrow(e) {
      const t = e.target;
      t.style.height = "auto";
      t.style.height = Math.min(t.scrollHeight, 140) + "px";
    },
    onKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    },
    clearHistory() {
      localStorage.removeItem("rag_messages_" + this.threadId);
      localStorage.removeItem("rag_thread_id");
      this.threadId = this.newThreadId();
      localStorage.setItem("rag_thread_id", this.threadId);
      this.messages = [{ role: "bot", content: WELCOME }];
    },
    saveSession() {
      if (!this.isStreaming) {
        localStorage.setItem("rag_messages_" + this.threadId, JSON.stringify(this.messages));
      }
    },
    async send() {
      const text = this.draft.trim();
      if (!text || this.isStreaming) return;

      this.stopRequested = false;
      this.messages.push({ role: "user", content: text });
      this.draft = "";
      if (this.$refs.input) this.$refs.input.style.height = "auto";

      this.messages.push({ role: "bot", content: "", streaming: true, sources: [] });
      const bot = this.messages[this.messages.length - 1];
      this.scrollToBottom();

      this.isStreaming = true;
      this.abortController = new AbortController();
      this.streamReader = null;
      let finished = false;
      try {
        const resp = await fetch("/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + this.token,
          },
          body: JSON.stringify({ message: text, thread_id: this.threadId }),
          signal: this.abortController.signal,
        });
        if (resp.status === 401) {
          this.logout();
          throw new Error("未授权，请重新登录");
        }
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        if (!resp.body) throw new Error("响应体为空");

        const reader = resp.body.getReader();
        this.streamReader = reader;
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (!finished) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";

          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;

            if (payload === "[DONE]") {
              finished = true;
              break;
            }

            let data;
            try {
              data = JSON.parse(payload);
            } catch (e) {
              continue;
            }

            if (data.error) {
              bot.content += "\n[出错] " + data.error;
            } else if (data.sources) {
              bot.sources = data.sources;
              this.scrollToBottom();
            } else if (data.content) {
              bot.content += data.content;
              this.scrollToBottom();
            }
          }
        }
        if (!bot.content && !this.stopRequested) bot.content = "（未返回内容）";
      } catch (err) {
        if (!this.stopRequested && err.name !== "AbortError") {
          bot.content = "请求失败：" + err.message;
        }
      } finally {
        const wasStopped = this.stopRequested;
        bot.streaming = false;
        this.isStreaming = false;
        this.abortController = null;
        this.streamReader = null;
        if (wasStopped && !bot.content) {
          this.messages = this.messages.filter((m) => m !== bot);
        }
        this.stopRequested = false;
        this.saveSession();
        this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
      }
    },
    stopStreaming() {
      if (!this.isStreaming) return;
      this.stopRequested = true;
      if (this.streamReader) {
        this.streamReader.cancel().catch(() => {});
        this.streamReader = null;
      }
      if (this.abortController) {
        this.abortController.abort();
      }
      this.isStreaming = false;
    },

    // ===== 文档管理 =====
    mapDoc(d) {
      return {
        id: d.id,
        name: d.original_filename,
        size: d.file_size != null ? this.formatSize(d.file_size) : "-",
        time: d.created_at || "-",
      };
    },
    async loadDocuments() {
      try {
        const params = new URLSearchParams({
          page: String(this.page),
          page_size: String(this.pageSize),
        });
        if (this.docSearch) params.set("keyword", this.docSearch);
        const r = await this.apiFetch("/documents?" + params.toString());
        if (!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json();
        this.docs = (data.documents || []).map((d) => this.mapDoc(d));
        this.total = data.total || 0;
        this.totalPages = data.total_pages || 0;
      } catch (err) {
        console.error("加载文档列表失败:", err);
        this.docs = [];
        this.total = 0;
        this.totalPages = 0;
      }
    },
    // 搜索框输入：300ms 防抖，避免每个字符都触发后端请求
    onDocSearchInput(e) {
      this.docSearchInput = e.target.value;
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => {
        this.docSearch = this.docSearchInput.trim();
        this.page = 1;
        this.loadDocuments();
      }, 300);
    },
    // 翻页：越界或未变化则忽略
    goToPage(p) {
      if (p < 1 || p > this.totalPages || p === this.page) return;
      this.page = p;
      this.loadDocuments();
    },
    prevPage() {
      this.goToPage(this.page - 1);
    },
    nextPage() {
      this.goToPage(this.page + 1);
    },
    onPageSizeChange() {
      this.page = 1;
      this.loadDocuments();
    },
    triggerUpload() {
      if (this.uploading) return;
      this.$refs.file && this.$refs.file.click();
    },
    onPick(e) {
      this.addFiles(Array.from(e.target.files || []));
      e.target.value = "";
    },
    onDrop(e) {
      this.dragging = false;
      this.addFiles(Array.from(e.dataTransfer.files || []));
    },
    // 拖入/选择后立即上传并向量化（逐个上传以展示各自进度）
    async addFiles(files) {
      const valid = files.filter((f) => /\.(txt|pdf|csv|md)$/i.test(f.name));
      const invalid = files.length - valid.length;
      if (invalid > 0) alert("已忽略 " + invalid + " 个不支持的文件（仅支持 .txt, .pdf, .csv, .md）");
      if (!valid.length) return;

      this.uploading = true;
      try {
        for (const f of valid) {
          // 先 push，再从响应式数组取回代理对象，保证后续进度更新能触发视图刷新
          this.uploadingFiles.push({
            name: f.name,
            size: this.formatSize(f.size),
            percent: 0,
            phase: "uploading",
          });
          const entry = this.uploadingFiles[this.uploadingFiles.length - 1];
          try {
            const data = await this.uploadOne(f, entry);
            const info = data && data.documents && data.documents[0];
            if (info && info.deduplicated) {
              alert(`「${f.name}」已上传过，重复向量化`);
            }
          } catch (err) {
            alert(`「${f.name}」上传失败：` + err.message);
          } finally {
            this.uploadingFiles = this.uploadingFiles.filter((e) => e !== entry);
          }
        }
        await this.loadDocuments();
      } finally {
        this.uploading = false;
      }
    },
    // 用 XHR 上传单个文件，实时回报上传进度；传输完成后进入“向量化中”阶段
    uploadOne(file, entry) {
      return new Promise((resolve, reject) => {
        const form = new FormData();
        form.append("files", file);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/documents/upload");
        xhr.setRequestHeader("Authorization", "Bearer " + this.token);

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            entry.percent = Math.round((e.loaded / e.total) * 100);
            // 字节传输完成，剩下的是服务端向量化（无法精确测量，用不确定态）
            if (entry.percent >= 100) entry.phase = "vectorizing";
          }
        };
        xhr.upload.onload = () => {
          entry.percent = 100;
          entry.phase = "vectorizing";
        };
        xhr.onload = () => {
          if (xhr.status === 401) {
            this.logout();
            reject(new Error("未授权，请重新登录"));
            return;
          }
          if (xhr.status >= 200 && xhr.status < 300) {
            let data = null;
            try { data = JSON.parse(xhr.responseText); } catch (e) {}
            resolve(data);
          } else {
            let msg = "HTTP " + xhr.status;
            try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (e) {}
            reject(new Error(msg));
          }
        };
        xhr.onerror = () => reject(new Error("网络错误"));
        xhr.send(form);
      });
    },
    async removeDoc(id) {
      const doc = this.docs.find((d) => d.id === id);
      if (!doc) return;
      if (!confirm(`确定删除文档「${doc.name}」吗？`)) return;
      try {
        const r = await this.apiFetch("/documents/" + encodeURIComponent(doc.id), { method: "DELETE" });
        if (!r.ok) {
          let msg = "HTTP " + r.status;
          try { msg = (await r.json()).detail || msg; } catch (e) {}
          throw new Error(msg);
        }
        // 当前页只剩这一条：删完会变空，回退到上一页再重新拉取
        if (this.docs.length <= 1 && this.page > 1) {
          this.page -= 1;
        }
        await this.loadDocuments();
      } catch (err) {
        alert("删除失败：" + err.message);
      }
    },
    formatSize(bytes) {
      if (bytes < 1024) return bytes + " B";
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
      return (bytes / 1024 / 1024).toFixed(1) + " MB";
    },
  },
}).mount("#app");

import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  ArchiveRestore,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  GitBranch,
  History,
  LayoutDashboard,
  Loader2,
  LockKeyhole,
  Pin,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Trash2,
  Unplug,
  X,
} from "lucide-react";
import { api, ApiError, intentKey } from "./api";
import type {
  Binding,
  Campaign,
  CreateRequest,
  EditAction,
  Meta,
  Operation,
  Reference,
  References,
  Stream,
} from "./types";

const statusLabels: Record<string, string> = {
  pending: "Ожидает",
  running: "Выполняется",
  completed: "Выполнено",
  failed: "Ошибка",
  unknown: "Нужна сверка",
  resolved: "Принято из Keitaro",
};
const stepLabels: Record<string, string> = {
  create_campaign: "Создать кампанию",
  create_stream_0: "Настроить гео-поток",
  create_stream_1: "Добавить офферный поток",
  enable_campaign: "Проверить и включить",
  update_offers: "Обновить привязки",
};

function Status({ value }: { value: string }) {
  return (
    <span className={`badge ${value}`}>
      <span />
      {statusLabels[value] || value}
    </span>
  );
}

function Button({
  children,
  busy,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  return (
    <button {...props} disabled={props.disabled || busy}>
      {busy ? <Loader2 size={16} className="spin" /> : null}
      {children}
    </button>
  );
}

function ReferenceSelect({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: Reference[];
  value: number;
  onChange: (id: number) => void;
}) {
  return (
    <label className="field">
      {label}
      <select
        required
        value={value || ""}
        onChange={(e) => onChange(Number(e.target.value))}
      >
        <option value="" disabled>
          Выберите из Keitaro
        </option>
        {items
          .filter((i) => i.state !== "deleted")
          .map((item) => (
            <option key={item.id} value={item.id}>
              {item.name || item.domain || `#${item.id}`} · #{item.id}
            </option>
          ))}
      </select>
    </label>
  );
}

function OperationDetail({
  operation,
  retry,
  busy,
}: {
  operation: Operation;
  retry: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div className="operation-detail">
      <div className="row between">
        <strong>
          {operation.kind === "create_campaign"
            ? "Создание кампании"
            : `Публикация потока #${operation.stream_id}`}
        </strong>
        <Status value={operation.status} />
      </div>
      <code className="operation-id">{operation.id}</code>
      <ol className="steps">
        {operation.steps.map((step) => (
          <li key={step.name}>
            <span className={`step-icon ${step.status}`}>
              {step.status === "completed" ? <Check size={14} /> : <span />}
            </span>
            <div>
              <span>{stepLabels[step.name] || step.name}</span>
              <small>
                {statusLabels[step.status] || step.status} · попыток{" "}
                {step.attempts}
              </small>
              {step.error && <p className="text-error">{step.error}</p>}
            </div>
          </li>
        ))}
      </ol>
      {operation.error && <p className="notice error">{operation.error}</p>}
      {operation.status !== "completed" && operation.status !== "resolved" && (
        <Button
          className="button secondary"
          busy={busy}
          onClick={() => retry(operation.id)}
        >
          <RefreshCw size={15} />
          Продолжить / сверить
        </Button>
      )}
      {operation.steps.some((s) => s.before || s.after) && (
        <details className="audit">
          <summary>История изменений</summary>
          {operation.steps.map((s) => (
            <div key={s.name}>
              <strong>{stepLabels[s.name] || s.name}</strong>
              {s.before && (
                <>
                  <small>До</small>
                  <pre>{JSON.stringify(s.before, null, 2)}</pre>
                </>
              )}
              {s.after && (
                <>
                  <small>Подтверждено</small>
                  <pre>{JSON.stringify(s.after, null, 2)}</pre>
                </>
              )}
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

function OfferSearch({
  onAdd,
  disabled,
}: {
  onAdd: (id: number) => void;
  disabled: boolean;
}) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Reference[]>([]);
  const [chosen, setChosen] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      if (!query.trim()) {
        setOptions([]);
        return;
      }
      api<Reference[]>(`/offers?q=${encodeURIComponent(query)}`)
        .then((result) => {
          if (!cancelled) {
            setOptions(result);
            setError("");
          }
        })
        .catch((e: Error) => {
          if (!cancelled) setError(e.message);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);
  return (
    <div className="offer-search">
      <div className="search-input">
        <Search size={16} />
        <input
          aria-label="Поиск оффера по ID или названию"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setChosen(0);
          }}
          placeholder="Найти оффер по ID или названию"
          disabled={disabled}
        />
      </div>
      <select
        aria-label="Найденный оффер"
        value={chosen || ""}
        onChange={(e) => setChosen(Number(e.target.value))}
        disabled={disabled || !options.length}
      >
        <option value="">
          {query ? "Выберите оффер" : "Результаты поиска"}
        </option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            #{o.id} · {o.name}
          </option>
        ))}
      </select>
      <Button
        className="button secondary"
        disabled={disabled || !chosen}
        onClick={() => {
          onAdd(chosen);
          setChosen(0);
        }}
      >
        <Plus size={16} />
        Добавить
      </Button>
      {error && <small className="text-error">{error}</small>}
    </div>
  );
}

function BindingRow({
  binding,
  disabled,
  act,
}: {
  binding: Binding;
  disabled: boolean;
  act: (action: EditAction) => void;
}) {
  const [share, setShare] = useState(String(binding.share));
  useEffect(() => setShare(String(binding.share)), [binding.share]);
  return (
    <tr className={binding.removed ? "removed" : ""}>
      <td>
        <span className="offer-id">#{binding.offer_id}</span>
        <strong>{binding.name || `Оффер #${binding.offer_id}`}</strong>
        {binding.state === "disabled" && !binding.removed && (
          <small>Выключен в Keitaro</small>
        )}
      </td>
      <td>
        <div className="share-cell">
          {binding.removed ? (
            <span className="zero-share">0%</span>
          ) : (
            <>
              <input
                aria-label={`Доля оффера ${binding.offer_id}`}
                type="number"
                min="0"
                max="100"
                value={share}
                disabled={disabled || binding.state === "disabled"}
                onChange={(e) => setShare(e.target.value)}
                onBlur={() => {
                  if (share !== String(binding.share)) {
                    const n = Number(share);
                    if (
                      share !== "" &&
                      Number.isInteger(n) &&
                      n >= 0 &&
                      n <= 100
                    )
                      act({
                        action: "set_share",
                        offer_id: binding.offer_id,
                        share: n,
                      });
                    else setShare(String(binding.share));
                  }
                }}
              />
              <span>%</span>
              <button
                className={`icon-button ${binding.pinned ? "pinned" : ""}`}
                title={binding.pinned ? "Открепить долю" : "Закрепить долю"}
                aria-label={`${binding.pinned ? "Открепить" : "Закрепить"} долю оффера ${binding.offer_id}`}
                disabled={disabled || binding.state === "disabled"}
                onClick={() =>
                  act({
                    action: binding.pinned ? "unpin" : "pin",
                    offer_id: binding.offer_id,
                  })
                }
              >
                <Pin
                  size={15}
                  fill={binding.pinned ? "currentColor" : "none"}
                />
              </button>
            </>
          )}
        </div>
      </td>
      <td>
        <span className={`binding-state ${binding.removed ? "archived" : ""}`}>
          {binding.removed
            ? "Удалён из потока"
            : binding.pinned
              ? "Доля закреплена"
              : binding.state === "disabled"
                ? "Выключен"
                : "Автораспределение"}
        </span>
      </td>
      <td>
        {binding.removed ? (
          <Button
            className="text-button"
            disabled={disabled}
            onClick={() =>
              act({ action: "restore", offer_id: binding.offer_id })
            }
          >
            <ArchiveRestore size={15} />
            Bring back
          </Button>
        ) : (
          <Button
            className="icon-button danger"
            title="Удалить привязку"
            aria-label={`Удалить привязку оффера ${binding.offer_id}`}
            disabled={disabled}
            onClick={() =>
              act({ action: "remove", offer_id: binding.offer_id })
            }
          >
            <Trash2 size={16} />
          </Button>
        )}
      </td>
    </tr>
  );
}

function StreamCard({
  stream,
  busy,
  edit,
  publish,
  cancel,
  adopt,
}: {
  stream: Stream;
  busy: boolean;
  edit: (s: Stream, a: EditAction) => void;
  publish: (s: Stream) => void;
  cancel: (s: Stream) => void;
  adopt: (s: Stream) => void;
}) {
  const active = stream.bindings.filter(
    (b) => !b.removed && b.state === "active",
  );
  const sum = active.reduce((total, b) => total + b.share, 0);
  const disabled =
    busy || Boolean(stream.pending_operation_id) || stream.deleted;
  return (
    <article
      className={`stream-card ${stream.dirty ? "dirty" : ""} ${stream.deleted ? "deleted-stream" : ""}`}
    >
      <header>
        <div className="row">
          <span className="stream-icon">
            <GitBranch size={19} />
          </span>
          <div>
            <h3>{stream.name}</h3>
            <small>
              Поток #{stream.stream_id} · {stream.type}
            </small>
          </div>
        </div>
        <span
          className={`badge ${stream.deleted ? "failed" : stream.dirty ? "draft" : "synced"}`}
        >
          {stream.deleted
            ? "Удалён в Keitaro"
            : stream.dirty
              ? "Не опубликован"
              : "Синхронизирован"}
        </span>
      </header>
      {stream.editable ? (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Оффер</th>
                  <th>Доля трафика</th>
                  <th>Распределение</th>
                  <th>
                    <span className="sr-only">Действия</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {stream.bindings.map((b) => (
                  <BindingRow
                    key={b.offer_id}
                    binding={b}
                    disabled={disabled}
                    act={(a) => edit(stream, a)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="stream-summary">
            <span>
              {active.length} активных ·{" "}
              {stream.bindings.filter((b) => b.removed).length} в архиве
            </span>
            <strong className={sum === 100 ? "" : "text-warning"}>
              Всего {sum}%
            </strong>
          </div>
          {sum !== 100 && !stream.deleted && (
            <p className="inline-note">
              <CircleHelp size={15} />
              Это доли, прочитанные из Keitaro. Они будут пересчитаны при
              редактировании.
            </p>
          )}
          {!stream.deleted && (
            <div className="stream-tools">
              <OfferSearch
                disabled={disabled}
                onAdd={(id) => edit(stream, { action: "add", offer_id: id })}
              />
            </div>
          )}
        </>
      ) : (
        <div className="readonly-stream">
          <Radio size={22} />
          <div>
            <strong>Поток без офферов</strong>
            <p>
              Настройки фильтров и редиректа сохраняются в Keitaro. Здесь
              изменяются только привязки офферов.
            </p>
          </div>
        </div>
      )}
      {stream.pending_operation_id ? (
        <div className="stream-footer pending">
          <span>Публикация требует сверки. Продолжите операцию в истории.</span>
          <Button
            className="button secondary"
            disabled={busy}
            onClick={() => adopt(stream)}
          >
            Принять Keitaro
          </Button>
        </div>
      ) : (
        stream.dirty && (
          <div className="stream-footer">
            <span>Изменения пока только в черновике</span>
            <div className="row">
              <Button
                className="button ghost"
                disabled={busy}
                onClick={() => cancel(stream)}
              >
                <RotateCcw size={15} />
                Cancel
              </Button>
              <Button
                className="button primary"
                disabled={busy}
                onClick={() => publish(stream)}
              >
                <Send size={15} />
                Push в Keitaro
              </Button>
            </div>
          </div>
        )
      )}
    </article>
  );
}

export default function App() {
  const [page, setPage] = useState<"create" | "editor">("create");
  const [refs, setRefs] = useState<References | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [campaignId, setCampaignId] = useState(
    new URLSearchParams(location.search).get("campaign") || "",
  );
  const [busy, setBusy] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [lastOperation, setLastOperation] = useState<Operation | null>(null);
  const [requiresAuth, setRequiresAuth] = useState(false);
  const [token, setToken] = useState("");
  const [form, setForm] = useState<CreateRequest>({
    name: "",
    country: "",
    offer_id: 0,
    domain_id: 0,
    group_id: 0,
    traffic_source_id: 0,
  });

  const refreshHistory = useCallback(
    async () => setOperations(await api<Operation[]>("/operations")),
    [],
  );
  const initialize = useCallback(async () => {
    setInitializing(true);
    try {
      const configuration = await api<Meta>("/meta");
      setMeta(configuration);
      setRequiresAuth(false);
      if (configuration.configured) {
        const [references, availableCampaigns] = await Promise.all([
          api<References>("/references"),
          api<Campaign[]>("/campaigns"),
        ]);
        setRefs(references);
        setCampaigns(availableCampaigns);
        setForm((old) => ({
          ...old,
          domain_id: old.domain_id || configuration.defaults.domain_id || 0,
          group_id: old.group_id || configuration.defaults.group_id || 0,
          traffic_source_id:
            old.traffic_source_id ||
            configuration.defaults.traffic_source_id ||
            0,
        }));
      }
      await refreshHistory();
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.code === "unauthorized")
        setRequiresAuth(true);
      else setError((e as Error).message);
    } finally {
      setInitializing(false);
    }
  }, [refreshHistory]);
  useEffect(() => {
    void initialize();
    if (new URLSearchParams(location.search).has("campaign")) setPage("editor");
  }, [initialize]);

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      const failure = e as Error;
      setError(
        failure.message +
          (e instanceof ApiError && e.requestId
            ? ` · запрос ${e.requestId}`
            : ""),
      );
    } finally {
      setBusy(false);
    }
  }
  function replaceStream(stream: Stream) {
    setStreams((old) =>
      old.map((s) => (s.stream_id === stream.stream_id ? stream : s)),
    );
  }
  async function fetchStreams() {
    const id = Number(campaignId);
    if (!Number.isInteger(id) || id <= 0)
      throw new Error("Укажите положительный ID кампании");
    setStreams(await api<Stream[]>(`/campaigns/${id}/fetch`, "POST"));
    history.replaceState(null, "", `?campaign=${id}`);
    setNotice("Актуальные потоки загружены из Keitaro");
  }
  function acceptOperation(operation: Operation) {
    setLastOperation(operation);
    if (operation.status !== "completed")
      setError(
        operation.error ||
          "Операция не завершена. Откройте историю для продолжения.",
      );
  }
  async function createCampaign(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const operation = await api<Operation>(
        "/campaigns",
        "POST",
        form,
        intentKey("create", form),
      );
      acceptOperation(operation);
      await refreshHistory();
      if (operation.status === "completed") {
        setNotice("Кампания создана, оба потока проверены и включены");
        setCampaigns(await api<Campaign[]>("/campaigns"));
      }
    });
  }
  async function retry(id: string) {
    await run(async () => {
      const operation = await api<Operation>(`/operations/${id}/retry`, "POST");
      acceptOperation(operation);
      await refreshHistory();
      if (campaignId && operation.kind === "publish_stream")
        setStreams(await api<Stream[]>(`/campaigns/${campaignId}/streams`));
    });
  }
  function newCampaign() {
    sessionStorage.removeItem("intent:create");
    setForm((old) => ({ ...old, name: "", offer_id: 0 }));
    setLastOperation(null);
    setNotice("");
  }

  const dirtyCount = streams.filter((s) => s.dirty).length;
  const field = (name: keyof CreateRequest, value: string | number) => {
    setForm((old) => ({ ...old, [name]: value }));
    if (
      lastOperation?.kind === "create_campaign" &&
      lastOperation.status === "completed"
    )
      setLastOperation(null);
  };
  let content: ReactNode;

  if (requiresAuth)
    content = (
      <div className="auth-card">
        <LockKeyhole size={28} />
        <h2>Доступ к рабочему пространству</h2>
        <p>
          Введите токен обёртки APP_ACCESS_TOKEN. API-ключ Keitaro хранится
          только на сервере.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sessionStorage.setItem("app-token", token);
            void initialize();
          }}
        >
          <label className="field">
            Токен доступа
            <input
              type="password"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <Button className="button primary" busy={initializing}>
            Войти
          </Button>
        </form>
      </div>
    );
  else if (page === "create")
    content = (
      <>
        <div className="page-heading">
          <div>
            <span className="eyebrow">CAMPAIGNS</span>
            <h1>Новая кампания</h1>
            <p>Два потока. Одно понятное правило маршрутизации.</p>
          </div>
          <span className="environment">
            <ShieldCheck size={15} />
            Ключ на сервере
          </span>
        </div>
        <div className="create-layout">
          <form className="panel campaign-form" onSubmit={createCampaign}>
            <div className="section-title">
              <span className="section-icon">
                <Settings2 size={18} />
              </span>
              <div>
                <h2>Параметры кампании</h2>
                <p>Название, география и целевой оффер</p>
              </div>
            </div>
            <label className="field">
              Название кампании
              <input
                required
                maxLength={200}
                placeholder="Например, AU · November · Leadgen"
                value={form.name}
                onChange={(e) => field("name", e.target.value)}
              />
            </label>
            <div className="form-row">
              <label className="field">
                Страна для Google
                <select
                  required
                  value={form.country}
                  onChange={(e) => field("country", e.target.value)}
                >
                  <option value="" disabled>
                    Выберите страну
                  </option>
                  {refs?.countries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.code} · {c.name}
                    </option>
                  ))}
                </select>
                <small>Посетители из этой страны попадут в первый поток</small>
              </label>
              <label className="field">
                ID оффера
                <input
                  required
                  type="number"
                  min="1"
                  placeholder="Например, 3717"
                  value={form.offer_id || ""}
                  onChange={(e) => field("offer_id", Number(e.target.value))}
                />
                <small>Существующий оффер в Keitaro</small>
              </label>
            </div>
            <div className="form-divider" />
            <div className="section-title compact">
              <h2>Подключение к Keitaro</h2>
              <span className="muted">Справочники из API</span>
            </div>
            <ReferenceSelect
              label="Домен"
              items={refs?.domains || []}
              value={form.domain_id}
              onChange={(id) => field("domain_id", id)}
            />
            <div className="form-row">
              <ReferenceSelect
                label="Группа кампаний"
                items={refs?.groups || []}
                value={form.group_id}
                onChange={(id) => field("group_id", id)}
              />
              <ReferenceSelect
                label="Источник трафика"
                items={refs?.sources || []}
                value={form.traffic_source_id}
                onChange={(id) => field("traffic_source_id", id)}
              />
            </div>
            <div className="form-actions">
              <span>
                <ShieldCheck size={16} />
                Проверка перед включением
              </span>
              <Button
                className="button primary"
                type="submit"
                busy={busy}
                disabled={
                  !meta?.configured ||
                  !refs ||
                  (lastOperation?.kind === "create_campaign" &&
                    lastOperation.status === "completed")
                }
              >
                <Plus size={17} />
                Создать кампанию
              </Button>
            </div>
          </form>
          <aside className="flow-preview">
            <div className="preview-label">КАК ПОЙДЁТ ТРАФИК</div>
            <div className="traffic-entry">
              <Radio size={21} />
              <div>
                <strong>{form.name || "Ваша кампания"}</strong>
                <small>Входящий трафик</small>
              </div>
            </div>
            <div className="flow-line" />
            <div className="route-preview">
              <span className="route-number">1</span>
              <div>
                <span className="route-condition">
                  Страна {form.country || "XX"}
                </span>
                <strong>Google</strong>
                <small>https://google.com</small>
              </div>
              <ExternalLink size={17} />
            </div>
            <div className="flow-line" />
            <div className="route-preview offer">
              <span className="route-number">2</span>
              <div>
                <span className="route-condition">Все остальные</span>
                <strong>
                  {form.offer_id
                    ? `Оффер #${form.offer_id}`
                    : "Выбранный оффер"}
                </strong>
                <small>100% оставшегося трафика</small>
              </div>
              <GitBranch size={19} />
            </div>
            <p className="preview-note">
              <CircleHelp size={16} />
              Первый подходящий поток перехватывает посетителя. Кампания
              включится после настройки и проверки обоих потоков.
            </p>
          </aside>
        </div>
        {lastOperation?.kind === "create_campaign" && (
          <section className="panel result">
            <OperationDetail
              operation={lastOperation}
              retry={(id) => void retry(id)}
              busy={busy}
            />
            {lastOperation.status === "completed" && (
              <div className="row">
                <Button
                  className="button primary"
                  onClick={() => {
                    setCampaignId(String(lastOperation.campaign_id));
                    setPage("editor");
                    setStreams([]);
                  }}
                >
                  Открыть редактор
                  <ChevronRight size={16} />
                </Button>
                <Button className="button ghost" onClick={newCampaign}>
                  Новая кампания
                </Button>
              </div>
            )}
          </section>
        )}
      </>
    );
  else
    content = (
      <>
        <div className="page-heading">
          <div>
            <span className="eyebrow">STREAM EDITOR</span>
            <h1>Потоки и офферы</h1>
            <p>Изменяйте привязки в черновике и публикуйте, когда готовы.</p>
          </div>
          <span className="environment">
            <GitBranch size={15} />
            {dirtyCount
              ? `${dirtyCount} с изменениями`
              : "Рабочее пространство"}
          </span>
        </div>
        <section className="panel fetch-panel">
          <div>
            <h2>Выберите кампанию</h2>
            <p>Fetch загружает настройки непосредственно из Keitaro</p>
          </div>
          <div className="fetch-controls">
            <label className="sr-only" htmlFor="campaign-id">
              ID кампании
            </label>
            <input
              id="campaign-id"
              type="number"
              min="1"
              list="campaign-list"
              placeholder="ID кампании"
              value={campaignId}
              disabled={busy}
              onChange={(e) => {
                setCampaignId(e.target.value);
                setStreams([]);
              }}
            />
            <datalist id="campaign-list">
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </datalist>
            <Button
              className="button primary"
              busy={busy}
              disabled={!campaignId || !meta?.configured}
              onClick={() => void run(fetchStreams)}
            >
              <RefreshCw size={16} />
              Fetch streams
            </Button>
          </div>
        </section>
        {!streams.length ? (
          <section className="empty-editor">
            <div className="empty-icon">
              <GitBranch size={35} />
            </div>
            <h2>Здесь появятся потоки кампании</h2>
            <p>
              Укажите ID и нажмите Fetch streams.
              <br />
              Настройки Keitaro останутся без изменений.
            </p>
          </section>
        ) : (
          <>
            <div className="editor-help">
              <span>
                <Pin size={15} />
                Закреплённые доли сохраняются. Остаток делится поровну.
              </span>
              <span>
                <History size={15} />
                Удалённые привязки можно вернуть
              </span>
            </div>
            {streams.map((stream) => (
              <StreamCard
                key={stream.stream_id}
                stream={stream}
                busy={busy}
                edit={(s, action) =>
                  void run(async () =>
                    replaceStream(
                      await api<Stream>(
                        `/streams/${s.stream_id}/draft`,
                        "PATCH",
                        { ...action, version: s.version },
                      ),
                    ),
                  )
                }
                cancel={(s) =>
                  void run(async () =>
                    replaceStream(
                      await api<Stream>(
                        `/streams/${s.stream_id}/cancel`,
                        "POST",
                        { version: s.version },
                      ),
                    ),
                  )
                }
                adopt={(s) => {
                  if (
                    confirm(
                      "Принять текущее состояние Keitaro и отбросить локальный черновик? Это не отменит изменения, уже записанные в Keitaro.",
                    )
                  )
                    void run(async () => {
                      replaceStream(
                        await api<Stream>(
                          `/streams/${s.stream_id}/adopt-remote`,
                          "POST",
                          { version: s.version },
                        ),
                      );
                      await refreshHistory();
                    });
                }}
                publish={(s) =>
                  void run(async () => {
                    const body = { version: s.version };
                    const operation = await api<Operation>(
                      `/streams/${s.stream_id}/publish`,
                      "POST",
                      body,
                      intentKey(`publish:${s.stream_id}`, body),
                    );
                    acceptOperation(operation);
                    setStreams(
                      await api<Stream[]>(
                        `/campaigns/${s.campaign_id}/streams`,
                      ),
                    );
                    await refreshHistory();
                    if (operation.status === "completed")
                      setNotice("Привязки опубликованы и проверены в Keitaro");
                  })
                }
              />
            ))}
          </>
        )}
      </>
    );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            setPage("create");
          }}
        >
          <span className="brand-mark">k</span>
          <span>
            keitaro<span className="brand-desk">desk</span>
          </span>
        </a>
        <span className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</span>
        <nav>
          <button
            className={page === "create" ? "active" : ""}
            onClick={() => {
              setPage("create");
              setError("");
              setNotice("");
            }}
          >
            <Plus size={18} />
            Создать кампанию
          </button>
          <button
            className={page === "editor" ? "active" : ""}
            onClick={() => {
              setPage("editor");
              setError("");
              setNotice("");
            }}
          >
            <GitBranch size={18} />
            Редактор потоков
            {dirtyCount > 0 && <span className="nav-count">{dirtyCount}</span>}
          </button>
          <button
            onClick={() => {
              setShowHistory(true);
              void run(refreshHistory);
            }}
          >
            <History size={18} />
            История операций
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div>
            <span
              className={`connection-dot ${meta?.configured && refs ? "online" : ""}`}
            />
            <span>
              {meta?.configured && refs
                ? "Keitaro подключён"
                : "Ожидает подключения"}
            </span>
          </div>
          <small>Изменения под вашим контролем</small>
          <a href="/docs" target="_blank" rel="noreferrer">
            Документация API
            <ExternalLink size={13} />
          </a>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div>
            <LayoutDashboard size={16} />
            <span>Рабочее пространство</span>
            <ChevronRight size={14} />
            <strong>{page === "create" ? "Кампании" : "Редактор"}</strong>
          </div>
          <button
            className="icon-button"
            title="Обновить подключение"
            aria-label="Обновить подключение"
            disabled={busy || initializing}
            onClick={() => void initialize()}
          >
            <RefreshCw size={16} className={initializing ? "spin" : ""} />
          </button>
        </header>
        <main>
          {error && (
            <div className="notice error" role="alert">
              <Unplug size={18} />
              <span>{error}</span>
              <button
                className="icon-button"
                aria-label="Закрыть ошибку"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="notice success" role="status">
              <CheckCircle2 size={18} />
              <span>{notice}</span>
              <button
                className="icon-button"
                aria-label="Закрыть уведомление"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {meta?.demo_mode && (
            <div className="notice warning">
              <Radio size={18} />
              <span>
                Локальное демо. Запросы идут в симулятор; реальные кампании
                Keitaro не изменяются.
              </span>
            </div>
          )}
          {meta && !meta.configured && (
            <div className="notice warning">
              <LockKeyhole size={18} />
              <span>
                Укажите KEITARO_API_KEY в серверном .env и перезапустите
                backend. Ключ не нужно вводить в браузере.
              </span>
            </div>
          )}
          {content}
          <footer className="page-footer">
            <span>Keitaro Desk</span>
            <span>
              <ShieldCheck size={13} />
              Офферы сохраняются. Меняются только привязки.
            </span>
          </footer>
        </main>
      </div>
      {busy && (
        <div className="working" role="status">
          <Loader2 size={16} className="spin" />
          Выполняется запрос…
        </div>
      )}
      {showHistory && (
        <div className="drawer-backdrop" onClick={() => setShowHistory(false)}>
          <aside
            className="history-drawer"
            aria-label="История операций"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <div>
                <span className="eyebrow">AUDIT LOG</span>
                <h2>История операций</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Закрыть историю"
                onClick={() => setShowHistory(false)}
              >
                <X size={20} />
              </button>
            </header>
            {operations.length ? (
              operations.map((operation) => (
                <section key={operation.id}>
                  <time>
                    {new Date(operation.created_at).toLocaleString("ru-RU")}
                  </time>
                  <OperationDetail
                    operation={operation}
                    retry={(id) => void retry(id)}
                    busy={busy}
                  />
                </section>
              ))
            ) : (
              <p className="muted">
                Операций пока нет. Здесь появятся создание кампаний и публикации
                потоков.
              </p>
            )}
            <p className="drawer-note">
              <Activity size={15} />
              История сохраняется на сервере
            </p>
          </aside>
        </div>
      )}
    </div>
  );
}

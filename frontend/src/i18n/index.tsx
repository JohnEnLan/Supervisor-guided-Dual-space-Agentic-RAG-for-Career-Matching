import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";

import { EN_TRANSLATIONS } from "./en";

export type Language = "zh" | "en";
export type TranslationParams = Record<string, string | number>;
export type Translate = (key: string, params?: TranslationParams) => string;

export const LANGUAGE_STORAGE_KEY = "career_rag_lang_v1";

const ZH_DOCUMENT_TITLE = "Career RAG 答辩工作台";
const EN_DOCUMENT_TITLE = "Career RAG Workbench";
let memoryLanguage: Language = "zh";

export function translate(lang: Language, zhText: string): string {
  return lang === "zh" ? zhText : (EN_TRANSLATIONS[zhText] ?? zhText);
}

function interpolate(template: string, params?: TranslationParams): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match,
  );
}

function translateWithParams(
  lang: Language,
  key: string,
  params?: TranslationParams,
): string {
  return interpolate(translate(lang, key), params);
}

const defaultT: Translate = (key, params) => translateWithParams("zh", key, params);

type LanguageContextValue = {
  lang: Language;
  t: Translate;
  setLang: (lang: Language) => void;
};

const LanguageContext = createContext<LanguageContextValue>({
  lang: "zh",
  t: defaultT,
  setLang: () => undefined,
});

function readLanguage(): Language {
  if (typeof window === "undefined") return memoryLanguage;
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (stored === null) return memoryLanguage;
    if (stored === "zh" || stored === "en") {
      memoryLanguage = stored;
      return stored;
    }
    memoryLanguage = "zh";
    return "zh";
  } catch {
    return memoryLanguage;
  }
}

function persistLanguage(lang: Language): void {
  memoryLanguage = lang;
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  } catch {
    // Module memory keeps the choice for this browser session when storage is unavailable.
  }
}

export function resetLanguageForTests(): void {
  memoryLanguage = "zh";
  try {
    window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  } catch {
    // Tests that disable storage still need the module-memory reset.
  }
}

export function LanguageProvider({ children }: PropsWithChildren) {
  const [lang, setLanguageState] = useState<Language>(readLanguage);
  const setLang = useCallback((nextLanguage: Language) => {
    persistLanguage(nextLanguage);
    setLanguageState(nextLanguage);
  }, []);
  const t = useCallback<Translate>(
    (key, params) => translateWithParams(lang, key, params),
    [lang],
  );

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.title = lang === "zh" ? ZH_DOCUMENT_TITLE : EN_DOCUMENT_TITLE;
  }, [lang]);

  const value = useMemo(() => ({ lang, t, setLang }), [lang, setLang, t]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  return useContext(LanguageContext);
}

export function LanguageToggle({ className = "" }: { className?: string }) {
  const { lang, t, setLang } = useLanguage();
  const nextLanguage = lang === "zh" ? "en" : "zh";
  const label = t("当前语言：{current}；切换到 {target}", {
    current: lang === "zh" ? t("中文") : "English",
    target: nextLanguage === "zh" ? t("中文") : "English",
  });

  return (
    <button
      type="button"
      className={`v2-language-toggle ${className}`.trim()}
      aria-label={label}
      title={label}
      onClick={() => setLang(nextLanguage)}
    >
      {nextLanguage === "en" ? "EN" : t("中文")}
    </button>
  );
}

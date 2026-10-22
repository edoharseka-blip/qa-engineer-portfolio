import { useEffect, useRef } from "react";

export const rub = (v: number | null | undefined) => v == null ? "—" : v.toLocaleString("ru-RU") + " ₽";
export const km = (v: number | null | undefined) => v == null ? "—" : v.toLocaleString("ru-RU") + " км";
export const TRANS: Record<string, string> = { AT: "автомат", MT: "механика", AMT: "робот", CVT: "вариатор" };
export const DRIVE: Record<string, string> = { AWD: "полный", RWD: "задний", FWD: "передний" };
export const FUEL: Record<string, string> = { petrol: "бензин", diesel: "дизель", hybrid: "гибрид", electric: "электро", gas: "газ" };
export const SELLER: Record<string, string> = { private: "частник", dealer: "дилер" };
export const SOURCE: Record<string, string> = { demo: "Демо", apiad_avito: "Авито (ApiAd)", apiad_drom: "Дром (ApiAd)", autoru: "Авто.ру" };

export function timeOnly(iso: string | null) {
  return iso ? new Date(iso).toLocaleTimeString("ru-RU", { hour12: false }) : "—";
}
export function dateTime(iso: string | null) {
  return iso ? new Date(iso).toLocaleString("ru-RU", { hour12: false, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
}
export function ago(iso: string | null) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)} с назад`;
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}
export function scoreClass(label: string | null) {
  return label === "very_interesting" ? "s-great" : label === "worth_a_look" ? "s-good" : label === "normal" ? "s-norm" : "s-low";
}
export function useInterval(fn: () => void, ms: number | null) {
  const saved = useRef(fn);
  useEffect(() => { saved.current = fn; });
  useEffect(() => {
    if (ms == null) return;
    const id = setInterval(() => saved.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}
export const num = (v: string) => (v.trim() === "" ? undefined : Number(v.replace(/\s/g, "")));

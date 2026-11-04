import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "../lib/api";
import type { Job, JobEvent } from "../lib/types";
import { isActive } from "../lib/types";

export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const pages = useRef(1);
  const mounted = useRef(true);
  const requestSequence = useRef(0);
  const inFlight = useRef<number | null>(null);
  const refresh = useCallback(async () => {
    if (inFlight.current !== null) return;
    const request = ++requestSequence.current;
    inFlight.current = request;
    const current = () =>
      mounted.current && request === requestSequence.current;
    try {
      const responses = await Promise.all(
        Array.from({ length: pages.current }, (_, index) =>
          api.jobs(undefined, index * 100),
        ),
      );
      if (current()) {
        const unique = new Map(
          responses.flatMap((page) => page.items).map((job) => [job.id, job]),
        );
        setJobs(Array.from(unique.values()));
        setTotal(responses[0]?.total ?? 0);
        setError("");
      }
    } catch (failure) {
      if (current()) setError(errorText(failure));
    } finally {
      if (inFlight.current === request) inFlight.current = null;
      if (current()) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 2500);
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
      inFlight.current = null;
      window.clearInterval(timer);
    };
  }, [refresh]);
  const loadMore = () => {
    if (loadingMore || jobs.length >= total) return;
    pages.current += 1;
    setLoadingMore(true);
    void refresh();
  };
  return { jobs, total, loading, loadingMore, error, refresh, loadMore };
}

export function useJob(id: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const mounted = useRef(true);
  const requestSequence = useRef(0);
  const inFlight = useRef<number | null>(null);
  const currentId = useRef(id);
  const polling = useRef(true);
  currentId.current = id;
  const refresh = useCallback(async () => {
    if (!id) return;
    if (inFlight.current !== null) return;
    const request = ++requestSequence.current;
    inFlight.current = request;
    const current = () =>
      mounted.current &&
      currentId.current === id &&
      request === requestSequence.current;
    try {
      const [detail, log] = await Promise.all([api.job(id), api.events(id)]);
      if (current()) {
        setJob(detail);
        setEvents(log.items);
        setError("");
        polling.current = isActive(detail);
      }
    } catch (failure) {
      if (current()) setError(errorText(failure));
    } finally {
      if (inFlight.current === request) inFlight.current = null;
      if (current()) setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    mounted.current = true;
    polling.current = true;
    setJob(null);
    setEvents([]);
    setError("");
    setLoading(Boolean(id));
    if (id) void refresh();
    const timer = window.setInterval(() => {
      if (id && polling.current && !document.hidden) void refresh();
    }, 1800);
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
      inFlight.current = null;
      window.clearInterval(timer);
    };
  }, [id, refresh]);
  return { job, events, error, loading, refresh };
}

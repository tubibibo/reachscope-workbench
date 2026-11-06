import type { Data, Job } from "./types";
import { isRecord } from "./types";

export function jobConfig(job: Pick<Job, "config">): Data {
  return isRecord(job.config) ? job.config : {};
}

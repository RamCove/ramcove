/** Where the RamCove API lives, and the error it reports. Pages read it on the server only. */

export const API_ORIGIN = process.env.RAMCOVE_API_ORIGIN ?? "http://127.0.0.1:8787";

export type ApiError = { code: string; message: string; reference?: string };

export class ApiFailure extends Error {
  constructor(
    public status: number,
    public error: ApiError,
  ) {
    super(error.message);
  }
}

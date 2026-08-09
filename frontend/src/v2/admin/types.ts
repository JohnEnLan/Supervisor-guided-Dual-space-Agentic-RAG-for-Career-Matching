export type GuardedAdminRequest = <T>(request: () => Promise<T>) => Promise<T>;

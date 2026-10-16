export function createRequestQueue<T>(): (request: () => Promise<T>) => Promise<T> {
  let tail: Promise<void> = Promise.resolve();
  return (request) => {
    const response = tail.then(request);
    tail = response.then(
      () => undefined,
      () => undefined,
    );
    return response;
  };
}

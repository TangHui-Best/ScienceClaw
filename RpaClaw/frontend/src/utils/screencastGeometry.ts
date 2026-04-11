export interface ScreencastSize {
  width: number;
  height: number;
}

export interface ScreencastRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface ScreencastFrameMetadata {
  width?: number;
  height?: number;
  frameWidth?: number;
  frameHeight?: number;
  inputWidth?: number;
  inputHeight?: number;
}

interface MapClientPointArgs {
  clientX: number;
  clientY: number;
  containerRect: ScreencastRect;
  frameSize: ScreencastSize;
  inputSize: ScreencastSize;
}

const isPositive = (value: number | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

const pickDimension = (values: Array<number | undefined>, fallback: number) => {
  for (const value of values) {
    if (isPositive(value)) {
      return value;
    }
  }
  return fallback;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export const getFrameSizeFromMetadata = (
  metadata: ScreencastFrameMetadata | undefined,
  fallback: ScreencastSize,
): ScreencastSize => ({
  width: pickDimension([fallback.width, metadata?.frameWidth, metadata?.width], fallback.width),
  height: pickDimension([fallback.height, metadata?.frameHeight, metadata?.height], fallback.height),
});

export const getInputSizeFromMetadata = (
  metadata: ScreencastFrameMetadata | undefined,
  fallback: ScreencastSize,
): ScreencastSize => ({
  width: pickDimension([metadata?.inputWidth, metadata?.frameWidth, metadata?.width], fallback.width),
  height: pickDimension([metadata?.inputHeight, metadata?.frameHeight, metadata?.height], fallback.height),
});

export const computeContainRect = (
  containerSize: ScreencastSize,
  contentSize: ScreencastSize,
): ScreencastRect => {
  if (!isPositive(containerSize.width) || !isPositive(containerSize.height)) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  if (!isPositive(contentSize.width) || !isPositive(contentSize.height)) {
    return { left: 0, top: 0, width: containerSize.width, height: containerSize.height };
  }

  const scale = Math.min(
    containerSize.width / contentSize.width,
    containerSize.height / contentSize.height,
  );
  const width = contentSize.width * scale;
  const height = contentSize.height * scale;

  return {
    left: (containerSize.width - width) / 2,
    top: (containerSize.height - height) / 2,
    width,
    height,
  };
};

export const mapClientPointToViewportPoint = ({
  clientX,
  clientY,
  containerRect,
  frameSize,
  inputSize,
}: MapClientPointArgs): { x: number; y: number } | null => {
  if (!isPositive(containerRect.width) || !isPositive(containerRect.height)) {
    return null;
  }

  const contentRect = computeContainRect(
    { width: containerRect.width, height: containerRect.height },
    frameSize,
  );
  if (!isPositive(contentRect.width) || !isPositive(contentRect.height)) {
    return null;
  }

  const localX = clientX - containerRect.left;
  const localY = clientY - containerRect.top;
  const relativeX = localX - contentRect.left;
  const relativeY = localY - contentRect.top;

  if (
    relativeX < 0
    || relativeY < 0
    || relativeX > contentRect.width
    || relativeY > contentRect.height
  ) {
    return null;
  }

  const normalizedX = relativeX / contentRect.width;
  const normalizedY = relativeY / contentRect.height;

  return {
    x: clamp(normalizedX * inputSize.width, 0, inputSize.width),
    y: clamp(normalizedY * inputSize.height, 0, inputSize.height),
  };
};

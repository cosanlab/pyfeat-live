// frontend/src/lib/studio/signals.ts
// Causal per-feature signal chain: smooth → per-person baseline (z) → onsets.
//
// Everything here is time-based (seconds), never frame-based: live detection
// arrives at ~10–25 Hz and recorded sessions at 4.5–10 Hz, both irregular.
// Everything is causal (uses only past samples) so a live performance and its
// replay produce the same output.

/** One-Euro filter (Casiez et al. 2012): adaptive low-pass that smooths
 *  jitter when a signal is still and follows fast when it moves. */
export class OneEuro {
  private x: number | null = null;
  private dx = 0;
  private t = 0;

  constructor(
    private minCutoff = 1.0,
    private beta = 0.3,
    private dCutoff = 1.0,
  ) {}

  private static alpha(cutoff: number, dt: number): number {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  }

  /** Smoothed derivative (units / s) from the last update. */
  get velocity(): number {
    return this.dx;
  }

  filter(x: number, t: number): number {
    if (this.x === null) {
      this.x = x;
      this.t = t;
      return x;
    }
    const dt = t - this.t;
    if (dt <= 0) return this.x; // duplicate / out-of-order sample
    const rawDx = (x - this.x) / dt;
    this.dx += OneEuro.alpha(this.dCutoff, dt) * (rawDx - this.dx);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.dx);
    this.x += OneEuro.alpha(cutoff, dt) * (x - this.x);
    this.t = t;
    return this.x;
  }

  reset(): void {
    this.x = null;
    this.dx = 0;
    this.t = 0;
  }
}

/** Exponentially weighted running mean/variance with a time constant, so a
 *  person is compared against their OWN recent resting level. */
export class RunningBaseline {
  private mean = 0;
  private variance = 0;
  private start: number | null = null;
  private last = 0;

  constructor(
    /** Time constant (s) of the running mean/variance. */
    private tau = 20,
    /** Seconds after the first sample during which z is reported as 0. */
    private warmup = 3,
    /** Minimum σ: a near-static face must not turn tiny noise into huge z. */
    private sigmaFloor = 0.03,
  ) {}

  get calibrating(): boolean {
    return this.start === null || this.last - this.start < this.warmup;
  }

  /** z of x against the baseline BEFORE x is folded in (so an onset isn't
   *  diluted by itself), then update the baseline. */
  update(x: number, t: number): number {
    if (this.start === null) {
      this.start = t;
      this.last = t;
      this.mean = x;
      this.variance = 0;
      return 0;
    }
    const dt = t - this.last;
    if (dt <= 0) return this.z(x);
    const elapsed = t - this.start;
    const z = elapsed < this.warmup ? 0 : this.z(x);
    // Early on the effective time constant is the elapsed time, which makes
    // the mean a cumulative average until tau is reached (fast convergence).
    const tauEff = Math.min(this.tau, Math.max(elapsed, dt));
    const w = 1 - Math.exp(-dt / tauEff);
    const diff = x - this.mean;
    const incr = w * diff;
    this.mean += incr;
    this.variance = (1 - w) * (this.variance + diff * incr);
    this.last = t;
    return z;
  }

  private z(x: number): number {
    return (x - this.mean) / Math.max(Math.sqrt(this.variance), this.sigmaFloor);
  }

  reset(): void {
    this.mean = 0;
    this.variance = 0;
    this.start = null;
    this.last = 0;
  }
}

export interface Onset {
  t: number;
  /** z at the moment of crossing (emitted immediately for low latency). */
  strength: number;
}

/** Threshold crossing with hysteresis + refractory period on a z signal. */
export class OnsetDetector {
  private armed = true;
  private lastOnset = -Infinity;

  constructor(
    public on = 1.5,
    public off = 0.7,
    public refractory = 0.25,
  ) {}

  update(z: number, t: number): Onset | null {
    if (this.armed) {
      if (z >= this.on) {
        this.armed = false;
        // A crossing inside the refractory window is treated as part of the
        // previous event: it disarms (must fall below `off` again) but is
        // not reported, so jittery double-peaks produce one note.
        if (t - this.lastOnset >= this.refractory) {
          this.lastOnset = t;
          return { t, strength: z };
        }
      }
    } else if (z <= this.off) {
      this.armed = true;
    }
    return null;
  }

  reset(): void {
    this.armed = true;
    this.lastOnset = -Infinity;
  }
}

export interface ChannelOutput {
  /** Smoothed value in the feature's own units. */
  value: number;
  /** Smoothed rate of change (units / s). */
  velocity: number;
  /** z against this person's running baseline (0 while calibrating). */
  z: number;
  calibrating: boolean;
  onset: Onset | null;
}

export interface FeatureChannelOptions {
  minCutoff?: number;
  beta?: number;
  tau?: number;
  warmup?: number;
  sigmaFloor?: number;
  onsetOn?: number;
  onsetOff?: number;
  refractory?: number;
}

/** smooth → baseline → onset for one (person, feature). */
export class FeatureChannel {
  private smoother: OneEuro;
  private baseline: RunningBaseline;
  private onsets: OnsetDetector;

  constructor(o: FeatureChannelOptions = {}) {
    this.smoother = new OneEuro(o.minCutoff ?? 1.0, o.beta ?? 0.3);
    this.baseline = new RunningBaseline(o.tau ?? 20, o.warmup ?? 3, o.sigmaFloor ?? 0.03);
    this.onsets = new OnsetDetector(o.onsetOn ?? 1.5, o.onsetOff ?? 0.7, o.refractory ?? 0.25);
  }

  /** Smoothed rate of change (units / s) as of the last update. */
  get velocity(): number {
    return this.smoother.velocity;
  }

  update(x: number, t: number): ChannelOutput {
    const value = this.smoother.filter(x, t);
    const z = this.baseline.update(value, t);
    const calibrating = this.baseline.calibrating;
    const onset = calibrating ? null : this.onsets.update(z, t);
    return { value, velocity: this.smoother.velocity, z, calibrating, onset };
  }

  reset(): void {
    this.smoother.reset();
    this.baseline.reset();
    this.onsets.reset();
  }
}

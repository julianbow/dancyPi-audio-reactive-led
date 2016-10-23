from __future__ import print_function
#from __future__ import division
import numpy as np
from scipy.interpolate import interp1d
import scipy.fftpack
import config


class ExponentialFilter:
    """Simple exponential smoothing filter"""
    def __init__(self, val=0.0, alpha_decay=0.5, alpha_rise=0.5):
        """Small rise / decay factors = more smoothing"""
        assert 0.0 < alpha_decay < 1.0, 'Invalid decay smoothing factor'
        assert 0.0 < alpha_rise < 1.0, 'Invalid rise smoothing factor'
        self.alpha_decay = alpha_decay
        self.alpha_rise = alpha_rise
        self.value = val

    def update(self, value):
        if not isinstance(self.value, (int, long, float)):
            alpha = value - self.value
            alpha[alpha > 0.0] = self.alpha_rise
            alpha[alpha <= 0.0] = self.alpha_decay
        else:
            alpha = self.alpha_rise if value > self.value else self.alpha_decay
        self.value = alpha * value + (1.0 - alpha) * self.value
        return self.value


# FFT statistics for a few previous updates
_ys_historical_energy = np.tile(1.0, (config.N_SUBBANDS, config.N_HISTORY))


def beat_detect(ys):
    """Detect beats using an energy and variance theshold
    
    Parameters
    ----------
    ys : numpy.array
        Array containing the magnitudes for each frequency bin of the
        fast fourier transformed audio data.
    
    Returns
    -------
    has_beat : numpy.array
        Array of booleans indicating a beat was detected in each of the
        frequency bins of ys.
    current_energy / mean_energy : numpy.array
        Array containing the ratios of the energies relative to the
        historical average energy for each of the frequency bins. The energies
        are calculated as the square of the real FFT magnitudes
    ys_variance : numpy.array
        The historical variance of the energies associated with each frequency
        bin in ys.
    """
    global _ys_historical_energy
    # Beat energy criterion
    current_energy = ys * ys
    mean_energy = np.mean(_ys_historical_energy, axis=1)
    has_beat_energy = current_energy > mean_energy * config.ENERGY_THRESHOLD
    _ys_historical_energy = np.roll(_ys_historical_energy, shift=1, axis=1)
    _ys_historical_energy[:, 0] = current_energy
    # Beat variance criterion
    ys_variance = np.var(_ys_historical_energy, axis=1)
    has_beat_variance = ys_variance > config.VARIANCE_THRESHOLD
    # Combined energy + variance detection
    has_beat = has_beat_energy * has_beat_variance
    return has_beat, current_energy / mean_energy, ys_variance


def wrap_phase(phase):
    """Converts phases in the range [0, 2 pi] to [-pi, pi]"""
    return (phase + np.pi) % (2 * np.pi) - np.pi


ys_prev = None
phase_prev = None
dphase_prev = None


def onset(yt):
    """Detects onsets in the given audio time series data

    Onset detection is perfomed using an ensemble of three onset detection
    functions.
    
    The first onset detection function uses the rectified spectral flux (SF)
    of successive FFT data frames.
    The second onset detection function uses the normalized weighted phase
    difference (NWPD) of successive FFT data frames.
    The third is a rectified complex domain onset detection function.

    The product of these three functions forms an ensemble onset detection
    function that returns continuous valued onset detection estimates.

    Parameters
    ----------
    yt : numpy.array
        Array of time series data to perform onset detection on

    Returns
    -------
    SF : numpy.array
        Array of rectified spectral flux values
    NWPD : numpy.array
        Array of normalized weighted phase difference values
    RCD : numpy.array
        Array of rectified complex domain values
    
    References
    ----------
    Dixon, Simon "Onset Detection Revisted"
    """
    global ys_prev, phase_prev, dphase_prev
    xs, ys = fft_log_partition(yt, 
                               subbands=config.N_SUBBANDS, 
                               window=np.hamming,
                               fmin=1,
                               fmax=14000)
    #ys = music_fft(yt)
    magnitude = np.abs(ys)
    phase = wrap_phase(np.angle(ys))
    # Special case for initialization
    if ys_prev is None:
        ys_prev = ys
        phase_prev = phase
        dphase_prev = phase
    # Rectified spectral flux
    SF = np.abs(ys) - np.abs(ys_prev)
    SF[SF < 0.0] = 0.0
    # First difference of phase
    dphase = wrap_phase(phase - phase_prev)
    # Second difference of phase
    ddphase = wrap_phase(dphase - dphase_prev)
    # Normalized weighted phase deviation
    NWPD = np.abs(ddphase * magnitude) / magnitude
    # Rectified complex domain onset detection function
    RCD = np.abs(ys - ys_prev * dphase_prev)
    RCD[RCD < 0.0] = 0.0
    RCD = RCD
    # Update previous values
    ys_prev = ys
    phase_prev = phase
    dphase_prev = dphase
    # Replace NaN values with zero
    SF = np.nan_to_num(SF)
    NWPD = np.nan_to_num(NWPD)
    RCD = np.nan_to_num(RCD)
    return SF, NWPD, RCD


def rfft(data, window=None):
    if window is None:
        window = 1.0
    else:
        window = window(len(data))
    ys = np.abs(np.fft.rfft(data*window))
    xs = np.fft.rfftfreq(len(data), 1.0 / config.MIC_RATE)
    return xs, ys


def rfft_log_partition(data, fmin=30, fmax=20000, subbands=64, window=None):
    """Returns FFT partitioned into subbands that are logarithmically spaced"""
    xs, ys = rfft(data, window=window)
    xs_log = np.logspace(np.log10(fmin), np.log10(fmax), num=subbands * 32)
    f = interp1d(xs, ys)
    ys_log = f(xs_log)
    X, Y = [], []
    for i in range(0, subbands * 32, 32):
        X.append(np.mean(xs_log[i:i + 32]))
        Y.append(np.mean(ys_log[i:i + 32]))
    return np.array(X), np.array(Y)


def fft(data, window=None):
    if window is None:
        window = 1.0
    else:
        window = window(len(data))
    ys = np.fft.fft(data*window)
    xs = np.fft.fftfreq(len(data), 1.0 / config.MIC_RATE)
    return xs, ys


def fft_log_partition(data, fmin=30, fmax=20000, subbands=64, window=None):
    """Returns FFT partitioned into subbands that are logarithmically spaced"""
    xs, ys = fft(data, window=window)
    xs_log = np.logspace(np.log10(fmin), np.log10(fmax), num=subbands * 32)
    f = interp1d(xs, ys)
    ys_log = f(xs_log)
    X, Y = [], []
    for i in range(0, subbands * 32, 32):
        X.append(np.mean(xs_log[i:i + 32]))
        Y.append(np.mean(ys_log[i:i + 32]))
    return np.array(X), np.array(Y)
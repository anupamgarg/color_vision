import os
import glob
import numpy as np
import scipy.io as sio
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
from matplotlib.image import AxesImage

matplotlib.rcParams['pdf.fonttype'] = 42
plt.style.use('ggplot')


def get_params(file_path, analyzer_path):
    """
    Input path to mat file from stimulus computer that contains trial sequence info.
    :param file_path: String. File path for mat file from stimulus computer.
    :return: pandas.DataFrame. DataFrame containing all stimulus sequence information.
    """
    exp_params_all = sio.loadmat(file_path, squeeze_me=True, struct_as_record=False)
    analyzer_complete = sio.loadmat(analyzer_path, squeeze_me=True, struct_as_record=False)
    analyzer = analyzer_complete['Analyzer']

    x_size = analyzer.P.param[5][2]
    y_size = analyzer.P.param[6][2]

    # Create list of all trials from mat file.
    r_seed = []
    for key in exp_params_all:
        if key.startswith('randlog'):
            r_seed.append(key)

    # Pull all trial information into DataFrame. Includes all Hartley information and stimulus size
    all_trials = pd.DataFrame()
    for seed in sorted(r_seed):
        exp_params = exp_params_all[seed]
        columns = ['quadrant', 'kx', 'ky', 'bwdom', 'color']
        conds = pd.DataFrame(exp_params.domains.Cond, columns=columns)
        trials = pd.DataFrame(exp_params.seqs.frameseq, columns=['cond'])
        trials -= 1

        for column in columns:
            trials[column] = trials.cond.map(conds[column])

        trials['ori'] = np.degrees(np.arctan(trials.ky / trials.kx)) % 360
        trials['sf'] = np.sqrt((trials.kx/x_size)**2 + (trials.ky/y_size)**2)

        all_trials = pd.concat([all_trials, trials], axis=0, ignore_index=True)

    return all_trials


def build_image_array(image_path):
    """
    Build NumPy array of image files using raw image files created with get_images.m.
    :param image_path: String. Path to image files created with get_images.m.
    :return: numpy.ndarray. Array of raw image files in order.
    """
    print('Building array of image files.')
    image_files = list(glob.iglob(image_path + '*.mat'))
    image_array = np.zeros([130, 120, 3, len(image_files)])
    for i in range(len(image_files)):
        image_array[:, :, :, i] = sio.loadmat(image_path + 'imageArray' + str(i + 1) + '.mat')['image'][319:449,
                                                                                                        447:567, :]
    image_array = image_array.astype('uint8')
    np.save(image_path + 'image_array.npy', image_array)
    return image_array


def get_unique_trials(params_path):
    """
    Return DataFrame of unique trials from all trials. Can be used to check if certain trial numbers are missing.
    :param params_path: String. Path to mat file of parameters from stimulus computer.
    :return: pandas.DataFrame. DataFrame containing all stimulus sequence information with duplicate trials removed.
    """
    trials = get_params(params_path)
    trials_unique = trials.drop_duplicates()

    return trials_unique


def get_image_idx(trials, spike_times):
    """
    Return index of image presented at all specified spike times.
    AG: modified to use pandas.searchsorted for speed.
    :param trials: pandas.DataFrame. All stimulus information.
    :param spike_times: np.ndarray. All spike times.
    :return: pandas.Series. Image index (out of all stimuli possible) at each spike time from spike_times.
    """
    stim_idx = trials.stim_time.searchsorted(spike_times, side='right') - 1
    image_idx = trials.cond[stim_idx]
    return image_idx


def get_mean_image(trials, spike_times, image_array):
    """
    Get mean image at specified spike times.
    :param trials: pandas.DataFrame. All stimulus information including stimulus presented.
    :param spike_times: np.ndarray. All spike times.
    :param image_array: np.ndarray. Raw images for all possible stimuli.
    :return: np.ndarray. Mean image.
    """
    image_idx = get_image_idx(trials, spike_times)
    mean_image = np.mean(image_array[:, :, :, image_idx], axis=3)
    return mean_image


def get_mean_point(x, y, trials, spike_times, image_array):
    """
    Get mean point (x, y) of all images at specified spike times.
    :param x: Integer. X coordinate.
    :param y: Integer. Y coordinate.
    :param trials: pandas.DataFrame. All stimulus information including stimulus presented.
    :param spike_times: np.ndarray. All spike times.
    :param image_array: np.ndarray. Raw images for all possible stimuli.
    :return: Float. Mean point.
    """
    image_idx = get_image_idx(trials, spike_times)
    mean_point = np.mean(image_array[y, x, :, image_idx], axis=0)
    return mean_point


def get_stim_samples_fh(data_path, start_time, end_time=None):
    """
    Get starting sample index of each 20ms pulse from photodiode.
    :param file_path: String. Path to binary file from recording.
    :return: np.ndarray. Starting times of each stimulus (1 x nStimuli).
    """
    data = (np.memmap(data_path, np.int16, mode='r').reshape(-1, 129)).T
    if end_time is not None:
        data = pd.DataFrame(data[128, start_time * 25000:end_time * 25000], columns=['photodiode'])
    else:
        data = pd.DataFrame(data[128, start_time * 25000:], columns=['photodiode'])

    hi_cut = 1500
    lo_cut = 600

    from detect_peaks import detect_peaks
    peaks = detect_peaks(data.photodiode, mph=lo_cut, mpd=200)

    # import peakutils as peakutils
    # peaks = peakutils.indexes(data.photodiode, thres=(1100/data.photodiode.max()), min_dist=200)

    peaks_high = peaks[np.where(data.photodiode[peaks] > hi_cut)]
    peaks_low = peaks[np.where(np.logical_and(data.photodiode[peaks] > lo_cut, data.photodiode[peaks] < hi_cut))]

    # In case of signal creep, remove all low peaks between trials
    # Edited to keep peaks due to stuck frames and only remove if final peak to peak distance > 500 (due to end pulse)
    trial_break_idx = np.where(np.diff(peaks_high) > 5000)[0]
    ind_delete = []
    for i, idx in enumerate(trial_break_idx):
        if peaks_high[idx] - peaks_high[idx - 1] < 500:
            ind_delete.append(i)
        else:
            peaks_low_delete = np.where(np.logical_and(peaks_low > peaks_high[idx], peaks_low < peaks_high[idx+1]))
            peaks_low = np.delete(peaks_low, peaks_low_delete)
    trial_break_idx = np.delete(trial_break_idx, ind_delete)

    # Remove pulses from beginning and end of trial (onset and end pulses)
    trial_break_idx = np.sort(np.concatenate([trial_break_idx, trial_break_idx + 1]))

    peaks_high = np.delete(peaks_high, trial_break_idx)[1:-1]
    peaks = np.sort(np.concatenate([peaks_high, peaks_low]))

    # Find rising edges of photodiode and mark as trial beginning and end
    data_peaks = pd.DataFrame()
    data_peaks['photodiode'] = data.photodiode[peaks]

    data_peaks['high'] = data_peaks.photodiode > 1500
    high = data_peaks.index[data_peaks['high'] & ~ data_peaks['high'].shift(1).fillna(False)]

    data_peaks['low'] = data_peaks.photodiode < 1500
    low = data_peaks.index[data_peaks['low'] & ~ data_peaks['low'].shift(1).fillna(False)]

    stim_times = np.sort(np.concatenate([high, low])) + (start_time * 60 * 25000)

    data_folder = os.path.dirname(data_path)
    np.save(data_folder + '/stim_samples.npy', data_folder)
    return stim_times


def get_stim_samples_pg(data_path, start_time, end_time=None):
    data = (np.memmap(data_path, np.int16, mode='r').reshape(-1, 129)).T

    if end_time is not None:
        data = pd.DataFrame(data[128, start_time * 60 * 25000:end_time * 60 * 25000], columns=['photodiode'])
    else:
        data = pd.DataFrame(data[128, :], columns=['photodiode'])

    from detect_peaks import detect_peaks
    peaks = detect_peaks(data.photodiode, mph=1500, mpd=200)
    fst = np.array([peaks[0]])
    stim_times_remaining = peaks[np.where(np.diff(peaks) > 10000)[0] + 1]
    stim_times = np.append(fst, stim_times_remaining)
    stim_times += (start_time * 60 * 25000)
    # dropped = np.where(np.diff(peaks) < 500)[0]
    # peaks_correct = np.delete(peaks, dropped + 1)
    # stim_times = peaks_correct[1::19]

    np.save(os.path.dirname(data_path) + '/stim_samples.npy', stim_times)

    return stim_times


def analyzer_pg(analyzer_path):
    analyzer_complete = sio.loadmat(analyzer_path, squeeze_me=True, struct_as_record=False)
    analyzer = analyzer_complete['Analyzer']

    b_flag = 0
    if analyzer.loops.conds[len(analyzer.loops.conds) - 1].symbol[0] == 'blank':
        b_flag = 1

    if b_flag == 0:
        trial_num = np.zeros((len(analyzer.loops.conds) * len(analyzer.loops.conds[0].repeats),
                             (len(analyzer.loops.conds[0].symbol))))
    else:
        trial_num = np.zeros(((len(analyzer.loops.conds) - b_flag) * len(analyzer.loops.conds[0].repeats) +
                              len(analyzer.loops.conds[-1].repeats),
                              (len(analyzer.loops.conds[0].symbol))))

    for count in range(0, len(analyzer.loops.conds) - b_flag):
        trial_vals = np.zeros(len(analyzer.loops.conds[count].symbol))

        for count2 in range(0, len(analyzer.loops.conds[count].symbol)):
            trial_vals[count2] = analyzer.loops.conds[count].val[count2]

        for count3 in range(0, len(analyzer.loops.conds[count].repeats)):
            aux_trial = analyzer.loops.conds[count].repeats[count3].trialno
            trial_num[aux_trial - 1, :] = trial_vals

    for blank_trial in range(0, len(analyzer.loops.conds[-1].repeats)):
        aux_trial = analyzer.loops.conds[-1].repeats[blank_trial].trialno
        trial_num[aux_trial - 1, :] = np.array([256, 256])

    stim_time = np.zeros(3)
    for count4 in range(0, 3):
        stim_time[count4] = analyzer.P.param[count4][2]

    return trial_num, stim_time


def jrclust_csv(csv_path):
    sp = pd.read_csv(csv_path, names=['time', 'cluster', 'max_site'])
    return sp


def kilosort_info(data_folder):
    sp = pd.DataFrame()
    sp['time'] = np.load(data_folder + 'spike_times.npy').flatten() / 25000
    sp['cluster'] = np.load(data_folder + 'spike_clusters.npy')
    return sp


class PlotRF(object):
    """
    Use reverse correlation to plot average stimulus preceding spikes from each unit.
    """
    def __init__(self, trials=None, spike_times=None, image_array=None):
        """

        :param trials: pandas.DataFrame. Contains stimulus times and Hartley stimulus information.
        :param spike_times: np.ndarray. Contains all spike times (1 x nSpikes).
        :param image_array: np.ndarray. Contains all image data (height x width x 3 x nStimuli).
        """
        self.x = None
        self.y = None

        self.fig, self.ax = plt.subplots()
        self.ax.set_title('Receptive Field')
        self.fig2, self.ax2 = plt.subplots()

        self.slider_ax = self.fig.add_axes([0.2, 0.02, 0.6, 0.03], axisbg='yellow')
        self.slider = Slider(self.slider_ax, 'Value', 0, 0.20, valinit=0)
        self.slider.on_changed(self.update)
        self.slider.drawon = False

        self.trials = trials
        self.spike_times = spike_times[(spike_times > trials.stim_time.min() + 0.2) &
                                       (spike_times < trials.stim_time.max())]
        self.image_array = image_array
        self.starting_image = get_mean_image(self.trials, self.spike_times, self.image_array)

        self.l = self.ax.imshow(self.starting_image, picker=True)

        self.t = np.arange(-0.2, 0, 0.001)
        self.ydata = np.zeros(np.size(self.t))
        self.l2, = self.ax2.plot([], [], 'r-')
        self.ax2.set_xlim([-0.20, 0])

        self.fig.canvas.mpl_connect('pick_event', self.onpick)

    def update(self, value):
        """

        :param value: Float. Value from slider on image.
        :return: New image presented containing shifted time window.
        """
        spike_times_new = self.spike_times - value
        self.l.set_data(get_mean_image(self.trials, spike_times_new, self.image_array))
        self.slider.valtext.set_text('{:03.3f}'.format(value))
        self.fig.canvas.draw()

    def onpick(self, event):
        """

        :param event: Mouse click on image.
        :return: New data on figure l2 displaying average contrast over time at point clicked during event.
        """
        artist = event.artist
        if isinstance(artist, AxesImage):
            mouse_event = event.mouseevent
            self.x = int(np.round(mouse_event.xdata))
            self.y = int(np.round(mouse_event.ydata))
            for i, time in enumerate(self.t):
                spike_times_new_pick = (np.array(self.spike_times) + time).tolist()
                y_val = get_mean_point(self.x, self.y, self.trials, spike_times_new_pick, self.image_array)
                self.ydata[i] = np.mean(y_val)
            self.l2.set_data(self.t, self.ydata)
            self.ax2.set_title('Spike-Triggered Average for Point [%d, %d]' % (self.x, self.y))
            self.ax2.set_xlabel('Time Before Spike (seconds)')
            self.ax2.set_ylabel('Spike-Triggered Average')
            self.ax2.relim()
            self.ax2.autoscale_view(True, True, True)
            self.fig2.canvas.draw()

    def show(self):
        """

        :return: Image displayed.
        """
        plt.show()


class GetLayers(object):
    """
    Plot CSD in interactive manner and allow clicks to get bottom and top of layer 4C.
    """
    # TODO write code to get bottom and top of granular layers

    def __init__(self, csd_data=None):
        self.x = None
        self.y = None

        self.csd_data = csd_data

    def onpick(self, event):
        artist = event.artist
        if isinstance(artist, AxesImage):
            mouse_event = event.mouseevent
            self.x = int(np.round(mouse_event.xdata))
            self.y = int(np.round(mouse_event.ydata))


def xcorr(a, b, maxlag=50, spacing=1):
    """
    Computes cross-correlation of spike times held in vector a and b with shift ms precision
    :param a: first array to be compared
    :param b: second array to be compared
    :param maxlag: maximum time shift to compute
    :param spacing: spacing between time shifts
    :return: index of time shifts and array of number of occurrences
    """
    xcorr_array = np.zeros((maxlag/spacing * 2) + 1)
    index = np.arange(-maxlag, maxlag + 1)
    for i in np.arange(0, maxlag+1, spacing):
        if i == 0:
            common = np.intersect1d(a, b).size
            xcorr_array[maxlag] = common
        else:
            bins_sub = np.concatenate((a - (i-spacing), a-i))
            bins_sub.sort()
            bins_add = np.concatenate((a + (i-spacing), a+i+0.0001))
            bins_add.sort()

            hist_sub = np.histogram(b, bins_sub)[0][0::2].sum()
            hist_add = np.histogram(b, bins_add)[0][0::2].sum()

            xcorr_array[np.abs(i-maxlag)] = hist_sub
            xcorr_array[i + maxlag] = hist_add

    return xcorr_array, index


def xcorr_spiketime_all(sp, maxlag=50, spacing=1):
    """
    Computes cross-correlation using spike times, computes all possible combinations between many pairs of neurons.
    :param sp: pandas.DataFrame of all spike times
    :param maxlag: maximum time shift to compute
    :param spacing: spacing between time shifts
    :return:
        dictionary of correlation, dictionary of indexes
    """
    from itertools import combinations

    clusters = sp[sp.cluster > 0].cluster.unique()
    clusters.sort()
    comb = list(combinations(clusters, 2))

    xcorr_dict = {}
    index_dict = {}

    for i in comb:
        xcorr_array, index = xcorr(sp[sp.cluster == i[0]].time, sp[sp.cluster == i[1]], maxlag, spacing)
        xcorr_dict[i] = xcorr_array
        index_dict[i] = index

    return xcorr_dict, index_dict


def xcorr_sp(data_folder, sp, maxlags=50, shift=1, cp_sig=0.1):
    """
    Computes cross-correlation using spike bins, computes all possible combinations between many pairs of neurons.
    :param sp: pandas.DataFrame of all spike times
    :param maxlags: maximum time shift to compute
    :param spacing: spacing between time shifts
    :return:
        dictionary of correlation, dictionary of indexes
    """
    sp['time_ms'] = sp.time * 1000
    binned = pd.DataFrame()
    bins = np.arange(0, int(np.ceil(sp.time_ms.max())), shift)
    for i in np.sort(sp[sp.cluster > 0].cluster.unique()):
        binned[i] = np.histogram(sp[sp.cluster == i].time_ms, bins)[0]

    binned_shuff = binned.reindex(np.random.permutation(binned.index))
    binned_shuff = binned_shuff.reindex()
    binned_shuff.index = binned.index

    index = np.arange(-maxlags, maxlags+1, shift)
    from itertools import combinations
    xcorr = pd.DataFrame(0, index=index, columns=list(combinations(binned.columns, 2)))
    xcorr_shuff = pd.DataFrame(0, index=index, columns=list(combinations(binned.columns, 2)))

    count = 0
    for i in binned.columns:
        nonzero_bins = binned[i].nonzero()[0]
        for j in np.arange(0, maxlags+1, shift):
            corr_add = binned.loc[nonzero_bins + j/shift].sum().as_matrix()
            corr_sub = binned.loc[nonzero_bins - j/shift].sum().as_matrix()

            corr_add_shuff = binned_shuff.loc[nonzero_bins + j/shift].sum().as_matrix()
            corr_sub_shuff = binned_shuff.loc[nonzero_bins - j/shift].sum().as_matrix()

            xcorr.loc[j, xcorr.columns[count:count + binned.columns.max() - i]] = corr_add[i:]
            xcorr.loc[-j, xcorr.columns[count:count + binned.columns.max() - i]] = corr_sub[i:]

            xcorr_shuff.loc[j, xcorr_shuff.columns[count:count + binned.columns.max()-i]] = corr_add_shuff[i:]
            xcorr_shuff.loc[-j, xcorr_shuff.columns[count:count + binned.columns.max()-i]] = corr_sub_shuff[i:]

        count += binned.columns.max()-i

    corr_prob = (xcorr.loc[0] - xcorr_shuff.loc[0]) / xcorr.sum()
    if not os.path.exists(data_folder + '/_images'):
        os.makedirs(data_folder + '/_images')

    plt.ioff()
    for i, corr_prob_sig_idx in enumerate(corr_prob[corr_prob > cp_sig].index):
        fig, ax = plt.subplots()
        ax.bar(index-(shift/2), xcorr[corr_prob_sig_idx], width=shift, color='#348ABD', alpha=0.5)
        ax.bar(index-(shift/2), xcorr_shuff[corr_prob_sig_idx], width=shift, color='#E24A33', alpha=0.5)

        max_site_1 = int(sp[sp.cluster == corr_prob_sig_idx[0]].max_site.mode())
        max_site_2 = int(sp[sp.cluster == corr_prob_sig_idx[1]].max_site.mode())

        ax.set_xlim([-maxlags, maxlags])
        ax.set_xlabel('Time (ms)')
        ax.set_ylabel('Number of Events')
        plt.suptitle('Cross-Correlogram for %s, CP = %.2f' % (str(corr_prob_sig_idx), corr_prob[corr_prob_sig_idx]))
        ax.set_title('Probe Sites: %d, %d' % (max_site_1, max_site_2), fontsize=10)

        plt.savefig(data_folder + '/_images/corr%d.pdf' % i, format='pdf')
        plt.close()
    plt.ion()

    return xcorr, xcorr_shuff

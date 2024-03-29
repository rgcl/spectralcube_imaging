#!/usr/bin/env python

import sys
from astropy.table import Table
import numpy as np
from astropy.io import fits
from scipy.stats import norm
from astropy import units as u
from scipy import interpolate
from scipy import integrate
import matplotlib
import matplotlib.pyplot as plt
import datetime


def read_spectralcube(fits_filename, hdu_data_index=1, hdu_header_units='BUNIT'):
    """
    Read the spectroscopic cube filename
    :param hdu_header_units:
    :param hdu_data_index:
    :param fits_filename: string
    :return: spectralcube in W/m**2/nm, hdu
    """
    with fits.open(fits_filename) as hdu:
        fits_units = u.Unit(hdu[hdu_data_index].header[hdu_header_units])
        cube_data = hdu[hdu_data_index].data

        ref_energy_units = u.Unit('W/m**2/nm')
        if fits_units != ref_energy_units:
            print(f'Cube is in {fits_units}, converting to {ref_energy_units}')
            cube_data = (cube_data * fits_units).to(ref_energy_units).value

        # take a slice as cube_data[index, :, :]
        return cube_data, hdu[hdu_data_index]


def normalize_filter(filter_data):
    """
    Use min-max normalization
    (https://en.wikipedia.org/wiki/Feature_scaling#Rescaling_.28min-max_normalization.29)
    :param filter_data:
    :return:
    """
    energy = filter_data[:, 1]
    filter_data[:, 1] = (energy - np.min(energy)) / (np.max(energy) - np.min(energy))
    return filter_data


def perform_with_filter_file(fits_filename, filter_filename): #(args):
    #fits_filename = args[0]
    #filter_filename = args[1]

    cube_data, hdu = read_spectralcube(fits_filename)

    filter_table = Table.read(filter_filename, format='ascii')
    filter_data = np.array([[item[0], item[1]] for item in filter_table.as_array()])

    # wavelengths converting from Angstrom to nm
    filter_data[:, 0] = (filter_data[:, 0] * u.Angstrom).to(u.nanometer).value

    # if the values are in photons, then convert to energy, multiplying lambda with photon
    if 'photon' in filter_table.meta['comments']:
        print(f'Filter is in "photons", converting to "energy"')
        filter_data[:, 1] = filter_data[:, 0] * filter_data[:, 1]

    #filter_data / np.

    perform(cube_data, hdu, normalize_filter(filter_data))


def perform_with_filter_range(fits_filename, lambda1, lambda2):
    lambda1 = float(lambda1)
    lambda2 = float(lambda2)
    cube_data, hdu = read_spectralcube(fits_filename)

    wavelength = np.linspace(lambda1, lambda2, 50 * (lambda2 - lambda1))
    mu = lambda1 + (lambda2 - lambda1) / 2
    energy = norm(mu, 1).pdf(wavelength)

    filter_data = np.array([[wl, e * wl] for wl, e in zip(wavelength, energy)])

    perform(cube_data, hdu, normalize_filter(filter_data))


def perform(cube_data, hdu, filter_data):
    """

    :param cube_data: in W/m**2/nm
    :param filter_data: in nm vs energy
    :return:
    """
    n_slices = cube_data.shape[0]
    CRVAL3 = hdu.header['CRVAL3']
    CD3_3 = hdu.header['CD3_3']
    CRPIX3 = hdu.header['CRPIX3']

    print('>> Calculating the lambda of each slice in the cube')

    # calculate the wavelength of each slice
    slices_lambda = (np.array([CRVAL3 + CD3_3 * (i - CRPIX3) for i in range(n_slices)]) * u.Angstrom).to(u.nm).value

    print('>> Interpolating to a common lambda base')
    # creating the based to interpolation (based in https://stackoverflow.com/a/49950451 )
    base_lambda = np.concatenate((slices_lambda, filter_data[:, 0]))
    base_lambda = np.unique(base_lambda) # this also sort

    plt.plot(base_lambda)
    plt.show()
    plt.figure()

    # because this is heavy computation, we change the type.
    # numpy.finfo(dtype('float16')) said that float16 can be at max 6.55040e+04,
    # so is cover for the wavelengths in nm
    slices_lambda = slices_lambda.astype(np.float32)
    base_lambda = base_lambda.astype(np.float32)
    #cube_data = cube_data.astype(np.float16)

    interpolate_cube = interpolate.interp1d(slices_lambda, cube_data, axis=0, assume_sorted=True)#, fill_value='extrapolate')
    cube_data_interpolated = interpolate_cube(base_lambda)

    interpolate_filter = interpolate.interp1d(filter_data[:, 0], filter_data[:, 1], fill_value='extrapolate')
    filter_data_interpolated = interpolate_filter(base_lambda)

    print('>> Preparing integration')

    # this is necessary in orden to multiply each slide with their correnpondent lambda filter
    for lambda_index in range(0, cube_data_interpolated.shape[0]):
        cube_data_interpolated[lambda_index, :, :] = \
            cube_data_interpolated[lambda_index, :, :] * filter_data_interpolated[lambda_index]

    print('>> Performing integration')

    integral_sup = integrate.trapz(cube_data_interpolated, x=base_lambda, axis=0)

    integral_sub = integrate.trapz(filter_data_interpolated, x=base_lambda)

    result = (integral_sup / integral_sub)

    # Saving the image
    hdu = fits.PrimaryHDU(result)
    hdr = hdu.header
    hdr['NAXIS'] = 2
    hdr['NAXIS1'] = result.shape[0]
    hdr['NAXIS2'] = result.shape[1]
    hdul = fits.HDUList([hdu])

    now = datetime.datetime.now()
    hdul.writeto(f'result_{now.strftime("%c")}.fits')

    print(result.shape)

    #plt.imshow(result, cmap='gray')
    #plt.colorbar()
    #plt.show()


if __name__ == '__main__':

    sys.argv.pop(0)
    argc = len(sys.argv)

    if argc == 2:
        perform_with_filter_file(*sys.argv)
    elif argc == 3:
        perform_with_filter_range(*sys.argv)
    else:
        print('>> Error: arguments must be 2 or 3')

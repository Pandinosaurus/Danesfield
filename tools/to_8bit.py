#!/usr/bin/env python

###############################################################################
# Copyright Kitware Inc. and Contributors
# Distributed under the Apache License, 2.0 (apache.org/licenses/LICENSE-2.0)
# See accompanying Copyright.txt and LICENSE files for details
###############################################################################


import argparse
import gdal
import logging
import numpy


def main(args):
    parser = argparse.ArgumentParser(
        description='Convert stretch the dynamic range of an image into 8 bits')
    parser.add_argument("source_image", help="Source image file name")
    parser.add_argument("destination_image", help="Destination image file name")
    parser.add_argument('-p', "--range-percentile", nargs=2, default=(0.1, 0.1), type=float,
                        help="The percent of smallest and largest intensities to "
                             "ignore when computing range for intensity scaling")
    args = parser.parse_args(args)

    if (args.range_percentile[0] < 0.0 or args.range_percentile[0] >= 50.0 or
            args.range_percentile[1] < 0.0 or args.range_percentile[1] >= 50.0):
                raise RuntimeError("Error: range percentile must be between 0 and 50")

    # open the source image
    source_image = gdal.Open(args.source_image, gdal.GA_ReadOnly)
    if not source_image:
        raise RuntimeError("Error: Failed to open source iamge {}".format(args.source_image))

    driver = source_image.GetDriver()
    driver_metadata = driver.GetMetadata()
    if driver_metadata.get(gdal.DCAP_CREATE) != "YES":
        raise RuntimeError("Error: driver {} does not supports Create().".format(driver))

    # Create the output RGB image
    print("Create destination byte image "
          "size:({}, {}) ...".format(source_image.RasterXSize,
                                     source_image.RasterYSize))
    num_bands = source_image.RasterCount
    projection = source_image.GetProjection()
    transform = source_image.GetGeoTransform()
    gcpProjection = source_image.GetGCPProjection()
    gcps = source_image.GetGCPs()
    options = ["COMPRESS=DEFLATE"]
    # ensure that space will be reserved for geographic corner coordinates
    # (in DMS) to be set later
    if (driver.ShortName == "NITF" and not projection):
        options.append("ICORDS=G")
    dest_image = driver.Create(args.destination_image,
                               xsize=source_image.RasterXSize,
                               ysize=source_image.RasterYSize,
                               bands=num_bands, eType=gdal.GDT_Byte,
                               options=options)

    # Copy over georeference information
    if (projection):
        # georeference through affine geotransform
        dest_image.SetProjection(projection)
        dest_image.SetGeoTransform(transform)
    else:
        # georeference through GCPs
        dest_image.SetGCPs(gcps, gcpProjection)

    # Copy the image data
    for idx in range(1, num_bands + 1):
        in_band = source_image.GetRasterBand(idx)
        out_band = dest_image.GetRasterBand(idx)
        # if not stretching to byte range, just copy the data

        in_data = in_band.ReadAsArray()
        # mask out pixels with no valid value
        in_no_data_val = in_band.GetNoDataValue()
        mask = in_data == in_no_data_val
        valid_data = in_data[numpy.logical_not(mask)]

        if valid_data.size > 0:
            # robustly find a range for intensity scaling
            min_p = args.range_percentile[0]
            max_p = 100.0 - args.range_percentile[1]
            min_val = numpy.percentile(valid_data, min_p)
            max_val = numpy.percentile(valid_data, max_p)
            print("band {} detected range: [{}, {}]".format(idx, min_val, max_val))

            # clip and scale the data to fit the range 1-255 and cast to byte
            in_data = in_data.clip(min_val, max_val)
            scale = 254.0 / float(max_val - min_val)
            in_data = (in_data - min_val) * scale + 1
        out_data = in_data.astype(numpy.uint8)
        # set the masked out invalid pixels to 0
        out_data[mask] = 0
        out_band.SetNoDataValue(0)
        out_band.WriteArray(out_data)


if __name__ == '__main__':
    import sys
    try:
        main(sys.argv[1:])
    except Exception as e:
        logging.exception(e)
        sys.exit(1)

#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
TrendFire.py: Python implementation of TrendFire.js using Earth Engine Python API.
This script calculates various vegetation, burn, and climate trends for a study area in Goa, India.

The script performs the following steps:
1. Processes Landsat 8 imagery for various spectral indices (NDVI, EVI, MSAVI, etc.)
2. Calculates long-term trends using linear regression for each index
3. Processes CHIRPS precipitation data and calculates rainfall trends
4. Processes SMAP soil moisture data and calculates soil moisture trends
5. Processes ERA5 relative humidity data and calculates humidity trends
6. Exports trend layers as GEE assets and local GeoTIFF files

Equivalent to the TrendFire.js script in the original implementation.
"""

import ee
import os
import datetime
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import geopandas as gpd
from tqdm import tqdm
from shapely.geometry import Polygon

# Initialize the Earth Engine API
def initialize_ee():
    try:
        ee.Authenticate()
        ee.Initialize()
        print("Earth Engine API initialized successfully.")
    except Exception as e:
        print(f"Error initializing Earth Engine API: {e}")
        print("Make sure you have authenticated with Earth Engine using ee.Authenticate()")

# Function to debug the shapefile
def debug_shapefile(boundary_path):
    """
    Debug function to check shapefile contents and geometry validity.
    """
    try:
        print("\nDebugging shapefile...")
        gdf = gpd.read_file(boundary_path)
        print(f"\nShapefile contains {len(gdf)} features")
        print("\nFirst few rows of the data:")
        print(gdf.head())
        print("\nGeometry type:", gdf.geometry.type.unique())
        print("\nCRS:", gdf.crs)
        
        # Check if geometries are valid
        invalid_geoms = gdf[~gdf.geometry.is_valid]
        if len(invalid_geoms) > 0:
            print("\nWarning: Found invalid geometries!")
            print("Number of invalid geometries:", len(invalid_geoms))
            print("\nInvalid geometries:")
            print(invalid_geoms)
        
        return gdf
    except Exception as e:
        print(f"Error debugging shapefile: {e}")
        return None

# Define the Goa study area boundary
def get_goa_boundary():
    """
    Get the boundary of the study area from the pa_boundary shapefile.
    Returns an ee.Geometry object.
    """
    try:
        # Try to load the boundary from the shapefile
        boundary_path = os.path.join('data', 'pa_boundary.shp')
        if os.path.exists(boundary_path):
            print("Loading study area boundary from shapefile...")
            
            # Debug the shapefile
            gdf = debug_shapefile(boundary_path)
            if gdf is None:
                return None
            
            # Ensure we have at least one valid geometry
            if len(gdf) == 0:
                print("Error: Shapefile contains no features")
                return None
            
            # Get the first geometry
            geometry = gdf.geometry.iloc[0]
            
            # Check if geometry is valid
            if not geometry.is_valid:
                print("Error: Geometry is invalid")
                return None
            
            # Convert 3D polygon to 2D by dropping Z coordinates
            if geometry.has_z:
                print("Converting 3D polygon to 2D...")
                # Get the coordinates and drop Z values
                coords = list(geometry.exterior.coords)
                coords_2d = [(x, y) for x, y, z in coords]
                # Create new 2D polygon
                geometry = Polygon(coords_2d)
            
            # Convert to GeoJSON
            gdf.geometry = gpd.GeoSeries([geometry])
            boundary_geojson = gdf.__geo_interface__
            
            # Create an EE geometry
            return ee.Geometry.Polygon(boundary_geojson['features'][0]['geometry']['coordinates'])
        else:
            print(f"Error: Could not find pa_boundary.shp at {boundary_path}")
            print("Please ensure the shapefile exists in the data directory")
            return None
    except Exception as e:
        print(f"Error loading boundary from shapefile: {e}")
        return None

# Function to mask clouds in Landsat 8 imagery
def maskL8sr(image):
    """
    Mask clouds and scale pixel values for Landsat 8 SR imagery.
    """
    # Get QA band
    qa = image.select('QA_PIXEL')
    
    # Bits 3 and 5 are cloud shadow and cloud, respectively
    cloud_shadow_bit_mask = 1 << 3
    clouds_bit_mask = 1 << 5
    
    # Both flags should be set to zero, indicating clear conditions
    mask = qa.bitwiseAnd(cloud_shadow_bit_mask).eq(0).And(
           qa.bitwiseAnd(clouds_bit_mask).eq(0))
    
    # Scale the optical bands
    optical_bands = image.select('SR_B.').multiply(0.0000275).add(-0.2)
    
    # Scale the thermal bands
    thermal_bands = image.select('ST_B.*').multiply(0.00341802).add(149.0)
    
    # Return the masked and scaled image
    return image.select(['QA_.*']).addBands(optical_bands).addBands(thermal_bands).updateMask(mask)

# Function to calculate spectral indices and add them as bands
def addIndices(image):
    """
    Calculate various spectral indices and add them as bands to the image.
    """
    # NDVI (Normalized Difference Vegetation Index)
    ndvi = image.normalizedDifference(['SR_B5', 'SR_B4']).rename('ndvi')
    
    # EVI (Enhanced Vegetation Index)
    evi = image.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {
            'NIR': image.select('SR_B5'),
            'RED': image.select('SR_B4'),
            'BLUE': image.select('SR_B2')
        }
    ).rename('evi')
    
    # MSAVI (Modified Soil Adjusted Vegetation Index)
    msavi = image.expression(
        '(2 * NIR + 1 - sqrt((2 * NIR + 1) * (2 * NIR + 1) - 8 * (NIR - RED))) / 2',
        {
            'NIR': image.select('SR_B5'),
            'RED': image.select('SR_B4')
        }
    ).rename('msavi')
    
    # MIRBI (Mid-Infrared Burn Index)
    mirbi = image.expression(
        '10 * SWIR2 - 9.8 * SWIR1 + 2',
        {
            'SWIR1': image.select('SR_B6'),
            'SWIR2': image.select('SR_B7')
        }
    ).rename('mirbi')
    
    # NDMI (Normalized Difference Moisture Index)
    ndmi = image.normalizedDifference(['SR_B5', 'SR_B6']).rename('ndmi')
    
    # NDFI (Normalized Difference Fraction Index)
    ndfi = image.normalizedDifference(['SR_B7', 'SR_B5']).rename('ndfi')
    
    # NBR (Normalized Burn Ratio)
    nbr = image.normalizedDifference(['SR_B5', 'SR_B7']).rename('nbr')
    
    # NBR2 (Normalized Burn Ratio 2)
    nbr2 = image.normalizedDifference(['SR_B6', 'SR_B7']).rename('nbr2')
    
    # BSI (Bare Soil Index)
    bsi = image.expression(
        '((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))',
        {
            'SWIR1': image.select('SR_B6'),
            'RED': image.select('SR_B4'),
            'NIR': image.select('SR_B5'),
            'BLUE': image.select('SR_B2')
        }
    ).rename('bsi')
    
    # Add all indices as bands
    return image.addBands([ndvi, evi, msavi, mirbi, ndmi, ndfi, nbr, nbr2, bsi])

# Function to calculate SMI (Soil Moisture Index)
def calculateSMI(image):
    """
    Calculate Soil Moisture Index (SMI) from Landsat data.
    """
    Ts = image.select('ST_B10')
    ndvi = image.select('ndvi')
    
    # Apply the SMI calculation
    smi = image.expression(
        '(Ts_max - Ts) / (Ts_max - Ts_min)',
        {
            'Ts': Ts,
            'Ts_max': Ts.reduceRegion(
                reducer=ee.Reducer.max(),
                geometry=image.geometry(),
                scale=30,
                maxPixels=1e9
            ).get('ST_B10'),
            'Ts_min': Ts.reduceRegion(
                reducer=ee.Reducer.min(),
                geometry=image.geometry(),
                scale=30,
                maxPixels=1e9
            ).get('ST_B10')
        }
    ).rename('smi')
    
    return image.addBands(smi)

# Main function to process Landsat 8 data and calculate trends
def process_landsat_trends(goa, start_date='2013-03-20', end_date='2023-02-28'):
    """
    Process Landsat 8 imagery, calculate vegetation indices and trends.
    """
    print("Processing Landsat 8 data and calculating trends...")
    
    # Load Landsat 8 collection and filter by date and location
    ls8_collection = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
        .filterDate(start_date, end_date) \
        .filterBounds(goa) \
        .filterMetadata('CLOUD_COVER', 'less_than', 10) \
        .map(maskL8sr) \
        .map(lambda image: image.clip(goa)) \
        .map(addIndices)
    
    # Calculate SWIR min/max for SMI calculation
    swir_stats = ls8_collection.mean().select('SR_B7').reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=goa,
        scale=30
    )
    
    swir_min = ee.Number(swir_stats.get('SR_B7_min'))
    swir_max = ee.Number(swir_stats.get('SR_B7_max'))
    
    # Function to calculate SMI using SWIR bands
    def addSMI(image):
        smi = image.select('SR_B7').subtract(swir_min) \
            .divide(swir_max.subtract(swir_min)) \
            .multiply(-1).add(1).rename('smi')
        return image.addBands(smi)
    
    # Add SMI to collection
    ls8_with_smi = ls8_collection.map(addSMI)
    
    # Select bands for trend analysis
    trend_bands = ['ndvi', 'evi', 'mirbi', 'ndfi', 'bsi', 'ndmi', 'nbr', 'nbr2', 'msavi', 'smi', 'ST_B10']
    ls8_with_smi = ls8_with_smi.select(trend_bands).sort('system:time_start')
    
    # Add a time band (in years)
    def addTimeBand(image):
        years = ee.Date(image.get('system:time_start')).difference(ee.Date(start_date), 'year')
        return image.addBands(ee.Image.constant(years).float().rename('time'))
    
    collection_with_time = ls8_with_smi.map(addTimeBand)
    
    # Calculate trends for each band and combine into a single image
    all_trends = None
    
    for band in trend_bands:
        print(f"Calculating trend for {band}...")
        
        # Select the index and time bands
        stacked = collection_with_time.select(['time', band])
        
        # Perform linear regression
        regression = stacked.reduce(ee.Reducer.linearFit())
        
        # Extract slope and intercept
        slope = regression.select('scale').rename(f'{band}_Slope')
        intercept = regression.select('offset').rename(f'{band}_Intercept')
        
        # Combine with previous trends
        if all_trends is None:
            all_trends = slope.addBands(intercept)
        else:
            all_trends = all_trends.addBands(slope).addBands(intercept)
    
    # Export the combined trends
    export_to_asset(
        all_trends,
        'users/jonasnothnagel/Trend2023_landsat',
        goa,
        'Landsat_Trends_2023',
        scale=30
    )
    
    return all_trends, ls8_with_smi

# Function to process CHIRPS precipitation data
def process_chirps_trends(goa, start_date='1982-01-01', end_date='2022-12-31'):
    """
    Process CHIRPS precipitation data and calculate rainfall trends.
    """
    print("Processing CHIRPS precipitation data and calculating trends...")
    
    # Load CHIRPS data
    chirps = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY') \
        .filterDate(start_date, end_date) \
        .filterBounds(goa)
    
    # Function to compute the yearly sum
    def createYearlySum(year):
        # Filter for the specific year
        year_filter = chirps.filter(ee.Filter.calendarRange(year, year, 'year'))
        
        # Create the yearly sum
        yearly_sum = year_filter.sum().clip(goa)
        
        # Add the year as a property
        return yearly_sum.set('year', year) \
                         .set('system:time_start', ee.Date.fromYMD(year, 1, 1).millis()) \
                         .rename('precipitation')
    
    # Create a list of yearly sums
    years = ee.List.sequence(1982, 2021)  # Match JS implementation
    yearly_sums = years.map(createYearlySum)
    
    # Convert to ImageCollection
    yearly_sums_collection = ee.ImageCollection.fromImages(yearly_sums)
    
    # Add time band
    def addTimeBand(image):
        time = ee.Date(image.get('system:time_start')).difference(ee.Date('1982-01-01'), 'year')
        return image.addBands(ee.Image.constant(time).rename('time').float())
    
    collection_with_time = yearly_sums_collection.map(addTimeBand)
    
    # Calculate trend
    stacked = collection_with_time.select(['time', 'precipitation'])
    regression = stacked.reduce(ee.Reducer.linearFit())
    slope = regression.select('scale').rename('rain_Slope')
    intercept = regression.select('offset').rename('rain_Intercept')
    trend = slope.addBands(intercept)
    
    # Export the trend
    export_to_asset(
        trend,
        'users/jonasnothnagel/Trend2022_rain_new',
        goa,
        'Precipitation_Trend_1982_2022',
        scale=30
    )
    
    return trend, yearly_sums_collection

# Function to process SMAP soil moisture data
def process_smap_trends(goa, start_date='2015-04-01', end_date='2023-02-28'):
    """
    Process SMAP soil moisture data and calculate trends.
    Note: SMAP data starts from April 2015.
    """
    print("Processing SMAP soil moisture data and calculating trends...")
    
    # Load SMAP data
    smap = ee.ImageCollection('NASA/SMAP/SPL3SMP_E/005') \
        .filterDate(start_date, end_date) \
        .filterBounds(goa) \
        .select(['soil_moisture_am']) \
        .map(lambda image: image.clip(goa))
    
    # Add time band
    def addTimeBand(image):
        time = ee.Date(image.get('system:time_start')).difference(ee.Date('2015-04-01'), 'year')
        return image.addBands(ee.Image.constant(time).rename('time').float())
    
    # Apply time band to each image in the collection
    soil_moisture_with_time = smap.map(addTimeBand)
    
    # Calculate trend
    regression = soil_moisture_with_time.reduce(ee.Reducer.linearFit())
    slope = regression.select('scale').rename('sm_surface_Slope')
    intercept = regression.select('offset').rename('sm_surface_Intercept')
    trend = slope.addBands(intercept)
    
    # Export the trend
    export_to_asset(
        trend,
        'users/jonasnothnagel/Trend2023_SM_new',
        goa,
        'SM_Trend2015_2023',
        scale=30
    )
    
    return trend, smap

# Function to process ERA5 relative humidity data
def process_era5_trends(goa, start_date='1980-01-01', end_date='2023-02-28'):
    """
    Process ERA5 data and calculate relative humidity trends.
    """
    print("Processing ERA5 relative humidity data and calculating trends...")
    
    # Load ERA5 data
    era5 = ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_AGGR") \
        .filterDate(start_date, end_date) \
        .filterBounds(goa) \
        .map(lambda image: image.clip(goa))
    
    # Function to calculate vapor pressure
    def calcVaporPressure(temp):
        denom = temp.add(243.5)
        num = temp.multiply(19.67)  # Note: JS uses 19.67 instead of 17.67
        exponent = num.divide(denom).exp()
        return exponent.multiply(6.112)
    
    # Calculate RH for each time step
    def calculateRH(image):
        dewPoint = image.select('dewpoint_temperature_2m')
        temperature = image.select('temperature_2m')
        
        # Calculate vapor pressures
        eT = calcVaporPressure(temperature)
        eTd = calcVaporPressure(dewPoint)
        
        # Compute relative humidity (%)
        RH = eTd.divide(eT).multiply(100).rename('RH')
        
        # Add time property
        return RH.set('system:time_start', image.get('system:time_start'))
    
    # Apply RH calculation to the collection
    rh_collection = era5.map(calculateRH)
    
    # Add time band
    def addTimeBand(image):
        time = ee.Date(image.get('system:time_start')).difference(ee.Date('1980-01-01'), 'year')
        return image.addBands(ee.Image.constant(time).rename('time').float())
    
    rh_with_time = rh_collection.map(addTimeBand)
    
    # Calculate trend
    regression = rh_with_time.reduce(ee.Reducer.linearFit())
    slope = regression.select('scale').rename('rh_Slope')
    intercept = regression.select('offset').rename('rh_Intercept')
    trend = slope.addBands(intercept)
    
    # Export the trend
    export_to_asset(
        trend,
        'users/jonasnothnagel/Trend2024_RH_new',
        goa,
        'RH_Trend1980_2023',
        scale=30
    )
    
    return trend, rh_collection

# Function to merge all trend layers
def merge_trend_layers(ls_trends, rain_trend, sm_trend, rh_trend):
    """
    Merge all trend layers into a single multi-band image.
    """
    # Combine all trend layers
    all_trends = ls_trends.addBands(rain_trend).addBands(sm_trend).addBands(rh_trend)
    
    return all_trends

# Function to export the trends to Google Earth Engine assets
def export_to_asset(image, asset_name, region, description=None, scale=30):
    """
    Export an image to a Google Earth Engine asset.
    """
    if description is None:
        description = asset_name.split('/')[-1]
    
    task = ee.batch.Export.image.toAsset(
        image=image,
        description=description,
        assetId=asset_name,
        region=region,
        scale=scale,
        maxPixels=1e13
    )
    
    task.start()
    print(f"Started export task: {description}")
    return task

# Function to export the trends to Google Drive
def export_to_drive(image, filename, region, description=None, folder='GEE_Exports', scale=30):
    """
    Export an image to Google Drive.
    """
    if description is None:
        description = filename
    
    task = ee.batch.Export.image.toDrive(
        image=image,
        description=description,
        folder=folder,
        fileNamePrefix=filename,
        region=region,
        scale=scale,
        maxPixels=1e13
    )
    
    task.start()
    print(f"Started export task to Drive: {description}")
    return task

def main():
    """
    Main function to process all trends and export results.
    """
    # Initialize Earth Engine
    initialize_ee()
    
    # Get Goa boundary
    print("Retrieving Goa boundary...")
    goa = get_goa_boundary()
    if goa is None:
        print("Error: Could not retrieve Goa boundary")
        return
    
    print("Successfully retrieved Goa boundary")
    
    # Process Landsat trends
    print("\nProcessing Landsat trends...")
    landsat_trends, landsat_collection = process_landsat_trends(goa)
    print("Landsat trends processed successfully")
    
    # Process CHIRPS precipitation trends
    print("\nProcessing CHIRPS precipitation trends...")
    rain_trends, rain_collection = process_chirps_trends(goa)
    print("CHIRPS precipitation trends processed successfully")
    
    # Process SMAP soil moisture trends
    print("\nProcessing SMAP soil moisture trends...")
    sm_trends, sm_collection = process_smap_trends(goa)
    print("SMAP soil moisture trends processed successfully")
    
    # Process ERA5 relative humidity trends
    print("\nProcessing ERA5 relative humidity trends...")
    rh_trends, rh_collection = process_era5_trends(goa)
    print("ERA5 relative humidity trends processed successfully")
    
    # Merge all trend layers
    print("\nMerging all trend layers...")
    all_trends = landsat_trends.addBands(rain_trends).addBands(sm_trends).addBands(rh_trends)
    
    # Export the merged trends
    print("Exporting merged trends...")
    export_to_asset(
        all_trends,
        'users/jonasnothnagel/Trend2024_all_new',
        goa,
        'All_Trends_2024',
        scale=30
    )
    
    print("\nAnalysis completed successfully!")
    print("Results exported to Earth Engine assets")
    
    return {
        'trends': all_trends,
        'collections': {
            'landsat': landsat_collection,
            'rain': rain_collection,
            'sm': sm_collection,
            'rh': rh_collection
        }
    }

if __name__ == "__main__":
    main() 
cmake_minimum_required(VERSION 3.28.0...3.31.0 FATAL_ERROR)

project(SLIAFlow)

# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/alejandrou/stratum")
set(EXTENSION_CATEGORY "STRATUM")
set(EXTENSION_CONTRIBUTORS "STRATUM project contributors")
set(EXTENSION_DESCRIPTION "Non-clinical STRATUM visualization prototype for 3D Slicer")
set(EXTENSION_ICONURL "")
set(EXTENSION_SCREENSHOTURLS "")
set(EXTENSION_DEPENDS "NA")

find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

add_subdirectory(SLIAFlow)

include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})

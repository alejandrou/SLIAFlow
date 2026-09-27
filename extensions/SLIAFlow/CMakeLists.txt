cmake_minimum_required(VERSION 3.28.0...3.31.0 FATAL_ERROR)

project(SLIAFlow)

# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/alejandrou/stratum")
set(EXTENSION_CATEGORY "STRATUM")
set(EXTENSION_CONTRIBUTORS "STRATUM project contributors")
set(EXTENSION_DESCRIPTION "Non-clinical STRATUM visualization prototype for 3D Slicer")
set(EXTENSION_ICONURL "")
set(EXTENSION_SCREENSHOTURLS "")
# The Connections section connects to IUMA's acquisition app as an OpenIGTLink
# client (ADR-0004 decision 2, SLIA-035). Declaring the dependency is what puts
# the pinned SlicerOpenIGTLink build into the generated launcher. The module
# still loads without it and says OpenIGTLink is not available.
set(EXTENSION_DEPENDS "SlicerOpenIGTLink")

find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

add_subdirectory(SLIAFlow)

include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})

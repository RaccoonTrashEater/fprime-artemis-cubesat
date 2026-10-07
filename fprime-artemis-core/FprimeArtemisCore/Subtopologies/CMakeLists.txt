####
# Project subtopologies. Registered from the top-level CMakeLists for the
# PayloadComputerDeployment (Linux) build only.
####
if (ARTEMIS_TARGET_ZEPHYR)
    add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/RadioComms")
else()
    add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/ArtemisDataProducts/")
endif()

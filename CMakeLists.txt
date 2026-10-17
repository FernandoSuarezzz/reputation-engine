cmake_minimum_required(VERSION 3.16)
project(ReputationEngine CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# With vcpkg: cmake -B build -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake
find_package(CURL REQUIRED)
find_package(nlohmann_json 3 REQUIRED)

add_executable(ReputationEngine src/reputation_engine.cpp)
target_link_libraries(ReputationEngine PRIVATE CURL::libcurl nlohmann_json::nlohmann_json)

if(MSVC)
  target_compile_options(ReputationEngine PRIVATE /W4 /utf-8)   # /utf-8: the source has accented string literals
  # std::getenv triggers warning C4996, which MSVC's SDL checks turn into an error
  target_compile_definitions(ReputationEngine PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
  target_compile_options(ReputationEngine PRIVATE -Wall -Wextra -Wpedantic)
endif()

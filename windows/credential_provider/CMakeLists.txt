# Build the FaceIQ credential provider DLL.
#   cmake -S . -B build -A x64
#   cmake --build build --config Release
# Produces build\Release\FaceIQCredentialProvider.dll
cmake_minimum_required(VERSION 3.20)
project(FaceIQCredentialProvider LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(FaceIQCredentialProvider SHARED
    Dll.cpp
    CFaceProvider.cpp
    CFaceCredential.cpp
    helpers.cpp
    FaceIpc.cpp
    FaceIQCredentialProvider.def
)

target_compile_definitions(FaceIQCredentialProvider PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN)

# SHStrDupW -> shlwapi; CredProtect -> credui; LSA -> secur32; HMAC/RNG -> bcrypt.
target_link_libraries(FaceIQCredentialProvider PRIVATE
    shlwapi credui secur32 bcrypt ole32 advapi32 user32)

set_target_properties(FaceIQCredentialProvider PROPERTIES OUTPUT_NAME "FaceIQCredentialProvider")

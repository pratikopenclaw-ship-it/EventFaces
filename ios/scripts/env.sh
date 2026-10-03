# Sourced by the other scripts. Uses /Applications/Xcode.app even if `xcode-select` still
# points at the Command Line Tools (run `sudo xcode-select -s /Applications/Xcode.app` to fix
# that globally).
if ! xcodebuild -version >/dev/null 2>&1; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
IOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$IOS_DIR/.." && pwd)"
SIM_IPHONE="${SIM_IPHONE:-iPhone 17}"
SIM_IPAD="${SIM_IPAD:-iPad Air 11-inch (M4)}"
# The screen matrix (ScreenMatrixUITests) also runs on the smallest and largest iPhones.
SIM_SMALL="${SIM_SMALL:-iPhone 17e}"
SIM_LARGE="${SIM_LARGE:-iPhone 18 Pro Max}"  # largest iPhone on the iOS 27 runtime
export IOS_DIR REPO_DIR SIM_IPHONE SIM_IPAD SIM_SMALL SIM_LARGE

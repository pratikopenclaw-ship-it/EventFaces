import CoreGraphics
import SwiftUI

/// One frame's measurements, in the server's (InsightFace) angle convention:
/// yaw > 0 = the person turned to THEIR left; pitch < 0 = looking down; roll: sign unused.
struct FrameMeasure: Equatable, Sendable {
    var faces: Int
    var yaw: Double?
    var pitch: Double?
    var roll: Double?
    var faceHeightRatio: Double?  // face height / frame height
    var brightness: Double?  // mean luma of the face, 0-255
    var center: CGPoint?  // normalized face centre, for stillness
}

/// The live hint. Same checks, order and thresholds as the web's `face-guidance.ts`
/// (thresholds come from /api/selfie-requirements); the server re-validates everything.
enum Guidance: Equatable, Sendable {
    case ok
    case noFace, multipleFaces, tooDark, tooBright, moveCloser, moveBack
    case raiseChin, lowerChin, keepHeadStraight, turnBack, lookStraight, turnLeft, turnRight

    var code: String {
        switch self {
        case .ok: "ok"
        case .noFace: "no_face"
        case .multipleFaces: "multiple_faces"
        case .tooDark: "too_dark"
        case .tooBright: "too_bright"
        case .moveCloser: "face_too_small"
        case .moveBack: "face_too_large"
        case .raiseChin, .lowerChin: "pitch_out_of_range"
        case .keepHeadStraight: "roll_out_of_range"
        case .turnBack: "yaw_out_of_range"
        case .lookStraight: "not_facing_camera"
        case .turnLeft: "wrong_turn_left"
        case .turnRight: "wrong_turn_right"
        }
    }

    var hint: LocalizedStringKey {
        switch self {
        case .ok: "Hold still"
        case .noFace: "Center your face in the oval"
        case .multipleFaces: "Make sure only you are in the picture"
        case .tooDark: "Too dark: face a window or lamp"
        case .tooBright: "Too bright: move out of direct light"
        case .moveCloser: "Move closer"
        case .moveBack: "Move back a little"
        case .raiseChin: "Raise your chin a little"
        case .lowerChin: "Lower your chin a little"
        case .keepHeadStraight: "Keep your head straight"
        case .turnBack: "Turn back toward the camera a little"
        case .lookStraight: "Face the camera"
        case .turnLeft: "Turn your head slightly to your left"
        case .turnRight: "Turn your head slightly to your right"
        }
    }

    static func evaluate(_ m: FrameMeasure, shot: CaptureShot, requirements r: SelfieRequirements) -> Guidance {
        guard m.faces > 0, let yaw = m.yaw, let pitch = m.pitch, let roll = m.roll, let ratio = m.faceHeightRatio else { return .noFace }
        if m.faces > 1 { return .multipleFaces }
        if let b = m.brightness, b < r.minBrightness { return .tooDark }
        if let b = m.brightness, b > r.maxBrightness { return .tooBright }
        if ratio < r.faceHeightMin { return .moveCloser }
        if ratio > r.faceHeightMax { return .moveBack }
        if abs(pitch) > r.maxPitch { return pitch < 0 ? .raiseChin : .lowerChin }
        if abs(roll) > r.maxRoll { return .keepHeadStraight }
        if abs(yaw) > r.maxYaw { return .turnBack }
        switch shot {
        case .front where abs(yaw) > r.frontMaxYaw: return .lookStraight
        case .left where yaw < r.sideMinYaw: return .turnLeft
        case .right where -yaw < r.sideMinYaw: return .turnRight
        default: return .ok
        }
    }

    /// True if the face centre moved less than `tolerance` (normalized) over the window.
    static func isStill(_ history: [CGPoint], tolerance: Double = 0.012) -> Bool {
        guard history.count >= 6 else { return false }
        let xs = history.map(\.x), ys = history.map(\.y)
        return (xs.max()! - xs.min()!) < tolerance && (ys.max()! - ys.min()!) < tolerance
    }
}

extension CaptureShot {
    var instruction: LocalizedStringKey {
        switch self {
        case .front: "Look straight at the camera"
        case .left: "Turn your head slightly to your left"
        case .right: "Turn your head slightly to your right"
        }
    }
}

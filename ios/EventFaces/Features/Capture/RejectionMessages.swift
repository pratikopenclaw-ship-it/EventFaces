import SwiftUI

/// The server's selfie rejection reasons (backend selfie_quality.MESSAGES), localized in the
/// app; unknown codes fall back to the server's (English) message.
enum RejectionMessages {
    static func text(code: String, serverMessage: String) -> Text {
        if let key = keys[code] { return Text(key) }
        return Text(verbatim: serverMessage)
    }

    nonisolated(unsafe) static let keys: [String: LocalizedStringKey] = [  // immutable literal
        "resolution_too_low": "The photo is too small. Use a camera with at least 640×480.",
        "no_face": "We couldn't find a face. Center your face in the oval.",
        "multiple_faces": "More than one face is visible. Make sure you're alone in the picture.",
        "low_confidence": "Your face isn't clearly visible. Remove sunglasses or a mask and face the light.",
        "face_too_small": "Move closer: your face should fill the oval.",
        "face_too_large": "Move back a little: your whole face should fit in the oval.",
        "yaw_out_of_range": "Turn your head less: look toward the camera.",
        "pitch_out_of_range": "Keep your head level: don't look up or down.",
        "roll_out_of_range": "Keep your head straight: don't tilt it sideways.",
        "not_facing_camera": "For the first photo, look straight at the camera.",
        "wrong_turn_left": "For this photo, turn your head slightly to your left.",
        "wrong_turn_right": "For this photo, turn your head slightly to your right.",
        "too_blurry": "The photo is blurry. Hold still and make sure the camera is in focus.",
        "too_dark": "It's too dark. Move to a brighter place or face a window.",
        "too_bright": "It's too bright. Avoid direct sunlight or strong light behind the camera.",
        "different_people": "The three photos don't seem to show the same person. Try again.",
        "unreadable": "We couldn't read this image.",
    ]
}

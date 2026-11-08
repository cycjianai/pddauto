import AppKit
import Foundation
import Vision

struct OCRRecord: Codable {
    let path: String
    let observations: [OCRObservation]
    let error: String?
}

struct OCRObservation: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

func recognize(path: String) -> OCRRecord {
    guard let image = NSImage(contentsOfFile: path),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return OCRRecord(path: path, observations: [], error: "image_decode_failed")
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.minimumTextHeight = 0.008

    do {
        try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
        let observations = (request.results ?? []).compactMap { observation -> OCRObservation? in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            let box = observation.boundingBox
            return OCRObservation(
                text: candidate.string,
                confidence: candidate.confidence,
                x: box.origin.x,
                y: box.origin.y,
                width: box.size.width,
                height: box.size.height
            )
        }
        return OCRRecord(path: path, observations: observations, error: nil)
    } catch {
        return OCRRecord(path: path, observations: [], error: String(describing: error))
    }
}

let paths = CommandLine.arguments.dropFirst()
let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]
for path in paths {
    let record = recognize(path: path)
    if let data = try? encoder.encode(record), let line = String(data: data, encoding: .utf8) {
        print(line)
    }
}

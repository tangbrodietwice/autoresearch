import Foundation

@MainActor func smoke() async {
    let api=Client()
    await api.connect()
    defer { api.stop() }
    func require(_ condition:Bool,_ message:String) throws {
        if !condition { throw APIError(message:message) }
    }
    func post(_ op:String,_ values:Record) async throws -> Record {
        var values=values; values["op"]=op
        return try await api.request("v1/action",values)
    }
    do {
        try require(api.connected,api.error)
        _ = try await post("settings",["slots":1,"delay":0.3])
        let plan = try await post("plan",["title":"Swift smoke","direction":"CTR"])
        let project = try await post("workspace",["name":"Smoke","repo":"mock","baseline":"v1","dataset":"synthetic-v1",
                                                  "train":"mock","evaluate":"mock","mode":"local","floor":0.715])
        let id=str(plan,"id")
        _ = try await post("attach",["id":id,"workspace":str(project,"id")])
        _ = try await post("start",["id":id,"budget":2])
        for _ in 0..<75 {
            try await api.refresh()
            let experiments=rows(api.data,"experiment")
            if experiments.count==2 {
                try require(rows(api.data,"task").contains{str($0,"status")=="completed"},"Task incomplete")
                _ = try await post("decision",["id":id,"value":"保留候选"])
                print("PASS Swift native client → bundled backend → two Git-backed experiments → decision")
                return
            }
            try await Task.sleep(for:.milliseconds(130))
        }
        throw APIError(message:"Experiments timed out")
    } catch {
        api.stop()
        FileHandle.standardError.write(Data("FAIL: \(error.localizedDescription)\n".utf8))
        exit(1)
    }
}

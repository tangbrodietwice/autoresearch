import SwiftUI
import AppKit

typealias Record = [String: Any]
func str(_ r: Record, _ key: String, _ fallback: String = "") -> String { r[key] as? String ?? fallback }
func num(_ r: Record, _ key: String, _ fallback: Int = 0) -> Int { r[key] as? Int ?? fallback }
func obj(_ r: Record, _ key: String) -> Record { r[key] as? Record ?? [:] }
func rows(_ r: Record, _ key: String) -> [Record] { r[key] as? [Record] ?? [] }
let modes = [("local","本机执行"),("hybrid","本机 Agent · 远端训练"),("remote","远端执行")]
func modeName(_ key: String) -> String { modes.first { $0.0 == key }?.1 ?? key }

struct APIError: LocalizedError { let message: String; var errorDescription: String? { message } }

@MainActor final class Client: ObservableObject {
    @Published var data: Record = [:]
    @Published var error = ""
    @Published var connected = false
    @Published var busy = false
    private var base: URL?
    private var process: Process?
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 12
        return URLSession(configuration: config)
    }()
    func connect() async {
        guard !connected else { return }
        do {
            if let url = ProcessInfo.processInfo.environment["TRIPSCI_URL"] { base = URL(string:url) }
            else {
                guard let script = Bundle.main.url(forResource:"app",withExtension:"py",subdirectory:"server") else { throw APIError(message:"找不到应用内的研究服务。") }
                let fm = FileManager.default
                let root = ProcessInfo.processInfo.environment["TRIPSCI_STATE"].map { URL(fileURLWithPath:$0) }
                    ?? fm.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("TripSci")
                try fm.createDirectory(at:root,withIntermediateDirectories:true)
                let p = Process(), pipe = Pipe()
                p.executableURL = URL(fileURLWithPath:"/usr/bin/env")
                var env = ProcessInfo.processInfo.environment
                env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
                p.environment = env
                p.arguments = ["python3",script.path,"--port","0","--state",root.path]
                p.standardOutput = pipe
                try p.run()
                process = p
                let line = await Task.detached { String(data:pipe.fileHandleForReading.availableData,encoding:.utf8) ?? "" }.value
                base = URL(string:line.trimmingCharacters(in:.whitespacesAndNewlines))
                if base?.scheme != "http" { throw APIError(message:"无法启动研究服务。请确认本机已安装 Python 3 和 Git。") }
            }
            try await refresh()
            connected = true
        } catch { self.error = error.localizedDescription }
    }
    func stop() { if let process, process.isRunning { process.terminate() }; session.invalidateAndCancel() }
    func refresh() async throws { data = try await request("v1/state") }
    func request(_ path: String, _ payload: Record? = nil) async throws -> Record {
        guard let base else { throw APIError(message:"研究服务还未连接。") }
        var req = URLRequest(url:base.appendingPathComponent(path))
        if let payload {
            req.httpMethod = "POST"
            req.setValue("application/json",forHTTPHeaderField:"Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject:payload)
            if payload["op"] as? String == "message" { req.timeoutInterval = 95 }
        }
        let (bytes,response) = try await session.data(for:req)
        let row = try JSONSerialization.jsonObject(with:bytes) as? Record ?? [:]
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw APIError(message:str(row,"error","请求失败。")) }
        return row
    }
    private var pendingActions: [Data: String] = [:]

    func action(_ payload: Record, then: @escaping (Record)->Void = {_ in}) {
        guard connected, !busy else { return }
        busy = true
        error = ""
        Task {
            defer { busy = false }
            do {
                let signature = try JSONSerialization.data(withJSONObject: payload, options: .sortedKeys)
                let key = pendingActions[signature] ?? UUID().uuidString
                pendingActions[signature] = key
                var requestPayload = payload
                requestPayload["request_key"] = key
                let result = try await request("v1/action", requestPayload)
                pendingActions.removeValue(forKey: signature)
                do { try await refresh() }
                catch { self.error = "操作已保存，暂未同步最新状态。" }
                busy = false
                then(result)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

}

let paper = Color(red:0.98,green:0.97,blue:0.94)
let clay = Color(red:0.56,green:0.27,blue:0.19)
struct TripMark: View {
    var size: CGFloat = 32
    var body: some View {
        Group {
            if let url = Bundle.main.url(forResource:"TripSci-icon",withExtension:"png"), let image = NSImage(contentsOf:url) {
                Image(nsImage:image).resizable().scaledToFit()
            } else { Image(systemName:"graduationcap.fill").foregroundStyle(clay) }
        }.frame(width:size,height:size).accessibilityHidden(true)
    }
}
struct Surface<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment:.leading,spacing:11) { content }
            .frame(maxWidth:.infinity,alignment:.leading).padding(16)
            .background(.background.opacity(0.75),in:RoundedRectangle(cornerRadius:12))
            .overlay(RoundedRectangle(cornerRadius:12).strokeBorder(.secondary.opacity(0.17)))
    }
}
enum Page: String, CaseIterable {
    case chat = "新聊天", plans = "研究计划", projects = "项目", agents = "智能体", settings = "设置"
    var icon: String { switch self {
    case .chat: "square.and.pencil"; case .plans: "checklist"; case .projects: "folder"; case .agents: "person.2"; case .settings: "gearshape"
    } }
}
enum Sheet: Identifiable {
    case workspace(Record,Bool), plan(String,Record), agent(Record)
    var id: String { switch self {case .workspace: "workspace"; case .plan: "plan"; case .agent: "agent"} }
}

struct RootView: View {
    @ObservedObject var api: Client
    @State private var page = Page.projects
    @State private var projectID = ""
    @State private var planID = ""
    @State private var threadID = ""
    @State private var agentID = ""
    @State private var sheet: Sheet?
    @State private var filter = "全部"
    var workspaces: [Record] { rows(api.data,"workspace") }
    var plans: [Record] { rows(api.data,"plan") }
    var agents: [Record] { rows(api.data,"agent") }
    var threads: [Record] { rows(api.data,"thread") }
    func find(_ rows:[Record],_ key:String) -> Record { rows.first { str($0,"id") == key } ?? [:] }
    func task(_ plan:Record) -> Record { find(rows(api.data,"task"),str(plan,"task")) }
    func status(_ plan:Record) -> String {
        if !str(plan,"decision").isEmpty { return "已完成" }
        return switch str(task(plan),"status") {case "waiting": "训练中"; case "ready": "待调度"; case "paused": "已暂停"; case "completed": "待评审"; default: "草稿"}
    }
    var sidebar: some View {
            VStack(alignment:.leading,spacing:6) {
                HStack { TripMark(); Text("TripSci").font(.system(.title2,design:.serif).bold()) }.padding(.bottom,12)
                ForEach(Page.allCases,id:\.self) { item in
                    nav(item.rawValue,item.icon,selected:page==item) {
                        page=item
                        switch item {
                        case .chat: threadID=""
                        case .plans: planID=""
                        case .agents: agentID=""
                        default: break
                        }
                    }
                }
                if !threads.isEmpty {
                    Text("最近聊天").font(.caption).foregroundStyle(.secondary).padding(.top,15)
                    ForEach(Array(threads.suffix(6).reversed()),id:\.identity) { row in
                        let id = str(row,"id")
                        let selected = page == Page.chat && threadID == id
                        nav(str(row,"title"),"bubble.left",selected:selected) { threadID=id; page = Page.chat }
                    }
                }
                Spacer()
                Label(api.connected ? "本地工作区 · 模拟训练" : "正在连接研究服务",systemImage:"circle.fill").font(.caption2).foregroundStyle(.secondary)
            }.padding(14).frame(width:200).background(.primary.opacity(0.035))
    }
    var body: some View {
        HStack(spacing:0) {
            sidebar
            Divider()
            Group {
                switch page {
                case .chat: chat
                case .plans: research
                case .projects: projects
                case .agents: agentView
                case .settings: SettingsView(api:api)
                }
            }.frame(maxWidth:.infinity,maxHeight:.infinity)
        }
        .background(paper).preferredColorScheme(.light).tint(clay)
        .frame(minWidth:890,minHeight:620)
        .sheet(item:$sheet) { item in
            switch item {
            case let .workspace(snapshot,attach):
                WorkspaceForm(api:api,row:snapshot,attachPlan:attach ? planID : "") { row in
                    projectID=str(row,"id"); sheet=nil
                    if !attach { page = .projects }
                }
            case let .plan(project,thread):
                PlanForm(api:api,projectID:project,thread:thread) { row in
                    sheet=nil; planID=str(row,"id"); page = .plans
                }
            case let .agent(snapshot):
                AgentForm(api:api,row:snapshot) { row in sheet=nil; agentID=str(row,"id") }
            }
        }
        .alert("TripSci",isPresented:Binding(get:{sheet == nil && !api.error.isEmpty},set:{if !$0 && sheet == nil {api.error=""}})) {
            Button("好"){api.error=""}
        } message: { Text(api.error) }
        .task {
            await api.connect()
            while !Task.isCancelled {
                try? await Task.sleep(for:.seconds(1))
                if api.connected && !api.busy { try? await api.refresh() }
            }
        }
    }
    func nav(_ label:String,_ icon:String,selected:Bool,action:@escaping ()->Void) -> some View {
        Button(action:action) {
            Label(label,systemImage:icon).lineLimit(1).frame(maxWidth:.infinity,alignment:.leading)
                .padding(.horizontal,8).padding(.vertical,7)
                .background(selected ? clay.opacity(0.11) : .clear,in:RoundedRectangle(cornerRadius:7))
        }.buttonStyle(.plain)
    }
    func openProject(_ row:Record = [:], attach:Bool = false) { api.error=""; sheet = .workspace(row,attach) }
    func title(_ text:String,_ subtitle:String) -> some View {
        VStack(alignment:.leading,spacing:5) {
            Text(text).font(.system(.largeTitle,design:.serif).bold())
            Text(subtitle).foregroundStyle(.secondary)
        }
    }
    var chat: some View {
        let row=find(threads,threadID)
        return VStack {
            if row.isEmpty {
                Spacer()
                TripMark(size:66)
                Text("今天想聊什么？").font(.system(.largeTitle,design:.serif).bold())
                Composer(placeholder:"自由讨论想法、运行问题或 Skills…") { text in
                    api.action(["op":"message","text":text]) { threadID=str($0,"id") }
                }.frame(maxWidth:630).padding(.top,10)
                Spacer()
            } else {
                HStack { Text(str(row,"title")).font(.headline); Spacer(); Button("创建研究计划"){api.error="";sheet = .plan("",row)} }.padding()
                Divider()
                Transcript(messages:rows(row,"messages"))
                Composer(placeholder:"继续聊天…") { text in api.action(["op":"message","thread":threadID,"text":text]) }.padding()
            }
        }.padding(row.isEmpty ? 24:0).id(threadID)
    }
    var research: some View {
        let plan=find(plans,planID)
        return Group {
            if !plan.isEmpty {
                PlanDetail(api:api,plan:plan,task:task(plan),state:status(plan),back:{planID=""},createProject:{openProject(attach:true)}).id(planID)
            } else {
                ScrollView {
                    VStack(alignment:.leading,spacing:16) {
                        HStack { title("研究计划","从一个值得验证的问题开始。"); Spacer(); Button("新建研究计划",systemImage:"plus"){api.error="";sheet = .plan("",[:])}.buttonStyle(.borderedProminent) }
                        if plans.isEmpty {
                            Surface { Text("还没有研究计划").font(.headline); Text("先记录标题与方向，可以稍后再关联项目。").foregroundStyle(.secondary) }
                        } else {
                            Picker("状态",selection:$filter) {
                                ForEach(["全部","草稿","待调度","训练中","已暂停","待评审","已完成"],id:\.self){Text($0)}
                            }.pickerStyle(.segmented)
                            ForEach(plans.filter{filter=="全部" || status($0)==filter},id:\.identity){ row in planRow(row) }
                        }
                    }.padding(30)
                }
            }
        }
    }
    func planRow(_ row:Record) -> some View {
        Button { planID=str(row,"id"); page = .plans } label: {
            Surface {
                HStack { Text(str(row,"title")).font(.headline); Spacer(); Text(status(row)).font(.caption); Image(systemName:"chevron.right").font(.caption) }
                Text(str(row,"direction")).foregroundStyle(.secondary).lineLimit(1)
            }
        }.buttonStyle(.plain)
    }
    var projects: some View {
        let selected=find(workspaces,projectID)
        let project = selected.isEmpty ? workspaces.first ?? [:] : selected
        let related=plans.filter { str($0,"workspace")==str(project,"id") }
        return ScrollView {
            VStack(alignment:.leading,spacing:17) {
                HStack {
                    title(project.isEmpty ? "从第一个研究项目开始" : str(project,"name"),project.isEmpty ? "配置代码、训练和评测入口，再创建第一项研究。" : "项目看板")
                    Spacer()
                    Button("新建项目",systemImage:"plus"){openProject()}.buttonStyle(.borderedProminent)
                }
                if !project.isEmpty {
                    Picker("项目",selection:Binding(get:{str(project,"id")},set:{projectID=$0})) {
                        ForEach(workspaces,id:\.identity){ Text(str($0,"name")).tag(str($0,"id")) }
                    }.frame(maxWidth:350)
                    Surface {
                        HStack { Text("项目配置 · v\(num(project,"version"))").font(.headline); Spacer(); Button("编辑配置"){openProject(project)} }
                        LabeledContent("执行环境",value:modeName(str(project,"mode")))
                        LabeledContent("默认基线",value:str(project,"baseline"))
                        LabeledContent("数据版本",value:str(project,"dataset"))
                        LabeledContent("训练与评测",value:str(project,"train")+" · "+str(project,"evaluate"))
                    }
                    Surface {
                        HStack { Text("研究计划").font(.headline); Spacer()
                            Button(related.isEmpty ? "创建第一项研究" : "新建计划"){api.error="";sheet = .plan(str(project,"id"),[:])} }
                        if related.isEmpty { Text("还没有研究计划。").foregroundStyle(.secondary) }
                        ForEach(related,id:\.identity){ planRow($0) }
                    }
                    Surface {
                        Text("近期实验").font(.headline)
                        let ids=Set(related.map{str($0,"task")})
                        let recent=rows(api.data,"experiment").filter{ids.contains(str($0,"task"))}
                        if recent.isEmpty { Text("等待第一条评测记录。").foregroundStyle(.secondary) }
                        ForEach(Array(recent.suffix(8).reversed()),id:\.identity) { ExperimentLine(row:$0) }
                    }
                }
            }.padding(30)
        }
    }
    var agentView: some View {
        let chosen=find(agents,agentID)
        return ScrollView {
            VStack(alignment:.leading,spacing:16) {
                HStack {
                    title(chosen.isEmpty ? "智能体" : str(chosen,"name"),"运行时、角色指令和 Skills")
                    Spacer()
                    Button("新建智能体",systemImage:"plus"){api.error="";sheet = .agent([:])}
                }
                if chosen.isEmpty {
                    ForEach(agents,id:\.identity){ row in
                        Button {agentID=str(row,"id")} label: {
                            Surface { HStack { Label(str(row,"name"),systemImage:"person.crop.circle"); Spacer(); Text(str(row,"runtime")).foregroundStyle(.secondary); Image(systemName:"chevron.right") } }
                        }.buttonStyle(.plain)
                    }
                } else {
                    Button("返回智能体列表"){agentID=""}.buttonStyle(.link)
                    Surface {
                        LabeledContent("配置版本",value:"v\(num(chosen,"version"))")
                        LabeledContent("运行时",value:"本机进程 · 模拟研究")
                        LabeledContent("Skills",value:(chosen["skills"] as? [String] ?? []).joined(separator:", "))
                        Text(str(chosen,"instructions"))
                        Button("编辑配置"){api.error="";sheet = .agent(chosen)}
                    }
                }
            }.padding(30)
        }
    }
}

extension Dictionary where Key == String, Value == Any {
    var identity: String { self["id"] as? String ?? "" }
}
struct Composer: View {
    let placeholder:String
    var send:(String)->Void
    @State private var input=""
    var body: some View {
        HStack(alignment:.center,spacing:8) {
            TextField(placeholder,text:$input,axis:.vertical).textFieldStyle(.plain).lineLimit(1...5)
                .onSubmit(submit)
            Button(action:submit) { Image(systemName:"arrow.up").frame(width:24,height:24) }
                .buttonStyle(.borderedProminent).disabled(input.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                .accessibilityLabel("发送消息")
        }.padding(10).background(.background,in:RoundedRectangle(cornerRadius:10))
            .overlay(RoundedRectangle(cornerRadius:10).strokeBorder(.secondary.opacity(0.25)))
    }
    func submit() { let value=input.trimmingCharacters(in:.whitespacesAndNewlines); if !value.isEmpty {send(value);input=""} }
}
struct Transcript: View {
    let messages:[Record]
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment:.leading,spacing:15) {
                    ForEach(Array(messages.enumerated()),id:\.offset) { item in
                        let role=str(item.element,"role")
                        HStack(alignment:.top,spacing:7) {
                            if role=="agent" { TripMark(size:25) }
                            Text(str(item.element,"text")).textSelection(.enabled)
                                .padding(9).background(role=="user" ? clay.opacity(0.10):.clear,in:RoundedRectangle(cornerRadius:8))
                        }.frame(maxWidth:.infinity,alignment:role=="user" ? .trailing:.leading)
                    }
                    Color.clear.frame(height:1).id("bottom")
                }.padding()
            }.onChange(of:messages.count,initial:true){_,_ in proxy.scrollTo("bottom",anchor:.bottom)}
        }
    }
}
struct ExperimentLine: View {
    let row:Record
    var body: some View {
        DisclosureGroup("第 \(num(row,"round")) 轮 · \(row["accepted"] as? Bool == true ? "采用" : "未采用")") {
            let metric=obj(row,"result")
            VStack(alignment:.leading,spacing:5) {
                Text("低频 AUC \(metric["low_freq_auc"] as? Double ?? 0,format:.number.precision(.fractionLength(4))) · 整体 AUC \(metric["overall_auc"] as? Double ?? 0,format:.number.precision(.fractionLength(4)))")
                if let passed=row["guardrail_passed"] as? Bool { Text(passed ? "护栏通过" : "护栏未通过").foregroundStyle(passed ? Color.secondary : Color.red) }
                Text("数据：\(str(row,"dataset"))")
                Text("代码：\(str(row,"revision"))").font(.caption.monospaced()).textSelection(.enabled)
                Text(str(row,"report")).font(.caption)
            }.frame(maxWidth:.infinity,alignment:.leading).padding(.vertical,6)
        }
    }
}
struct PlanDetail: View {
    @ObservedObject var api: Client
    let plan:Record
    let task:Record
    let state:String
    let back:()->Void
    let createProject:()->Void
    @State private var selected=""
    @State private var agent="worker"
    @State private var budget=3
    @State private var baseline=""
    @State private var feedback=""
    @State private var feedbackOpen=false
    @State private var confirm=false
    var id:String {str(plan,"id")}
    var env:Record { task.isEmpty ? rows(api.data,"workspace").first { str($0,"id")==str(plan,"workspace") } ?? [:] : obj(task,"environment") }
    var currentJob:Record { rows(api.data,"job").first{str($0,"id")==str(task,"pending_job")} ?? [:] }
    var body:some View {
        VStack(spacing:0) {
            HStack { Button("研究计划",systemImage:"chevron.left",action:back).buttonStyle(.plain)
                Spacer(); Text(state).font(.caption).padding(6).background(clay.opacity(0.12),in:Capsule()) }.padding(13)
            Divider()
            HStack(spacing:0) {
                VStack(alignment:.leading,spacing:0) {
                    VStack(alignment:.leading,spacing:6) {
                        Text(str(plan,"title")).font(.system(.title,design:.serif).bold())
                        Text(str(plan,"direction")).foregroundStyle(.secondary)
                    }.padding()
                    Transcript(messages:rows(plan,"messages"))
                    Composer(placeholder:"讨论实验计划或询问进展…") { text in api.action(["op":"message","plan":id,"text":text]) }.padding()
                }.frame(maxWidth:.infinity,maxHeight:.infinity)
                Divider()
                ScrollView {
                    VStack(alignment:.leading,spacing:13) {
                        Text("研究计划状态").font(.headline)
                        if task.isEmpty { draft } else { running }
                    }.padding(12)
                }.frame(width:325).background(.primary.opacity(0.025))
            }
        }.sheet(isPresented:$feedbackOpen) {
            VStack(alignment:.leading,spacing:12) {
                Text("给 Worker 反馈").font(.headline)
                Text("当前训练继续。支持「保守」或指定「强度 0.55」来改变后续实验。").foregroundStyle(.secondary)
                TextField("建议",text:$feedback).textFieldStyle(.roundedBorder)
                if !api.error.isEmpty { Text(api.error).font(.caption).foregroundStyle(.red) }
                HStack { Button("取消"){api.error="";feedbackOpen=false}; Spacer()
                    Button("发送反馈"){api.action(["op":"feedback","id":id,"text":feedback]) {_ in feedback="";feedbackOpen=false} }
                        .buttonStyle(.borderedProminent).disabled(feedback.isEmpty || api.busy)
                }
            }.padding(22).frame(width:380)
        }
        .confirmationDialog("锁定这份契约并启动模拟研究？",isPresented:$confirm,titleVisibility:.visible) {
            Button("确认并启动"){api.action(["op":"start","id":id,"agent":agent,"budget":budget,"baseline":baseline])}
        } message: {Text("\(modeName(str(env,"mode"))) · \(budget) 轮 · 护栏 \(env["floor"] as? Double ?? 0.715)")}
    }
    var draft:some View {
        Surface {
            if env.isEmpty {
                Text("尚未关联项目").font(.headline)
                Text("可以继续讨论。准备启动时再选择项目。").foregroundStyle(.secondary)
                Picker("项目",selection:$selected) {
                    Text("请选择").tag("")
                    ForEach(rows(api.data,"workspace"),id:\.identity){Text(str($0,"name")).tag(str($0,"id"))}
                }
                HStack {
                    Button("关联项目"){api.action(["op":"attach","id":id,"workspace":selected])}.disabled(selected.isEmpty || api.busy)
                    Button("新建项目",action:createProject)
                }
            } else {
                Text(str(env,"name")+" · 配置 v\(num(env,"version"))").font(.headline)
                LabeledContent("执行环境",value:modeName(str(env,"mode")))
                LabeledContent("默认基线",value:str(env,"baseline"))
                LabeledContent("数据",value:str(env,"dataset"))
                LabeledContent("整体 AUC 下限",value:String(env["floor"] as? Double ?? 0.715))
                TextField("实验基线（可覆盖默认）",text:$baseline)
                Picker("执行者",selection:$agent) {
                    ForEach(rows(api.data,"agent"),id:\.identity){Text(str($0,"name")+" · v\(num($0,"version"))").tag(str($0,"id"))}
                }
                Stepper("实验预算：\(budget) 轮",value:$budget,in:1...10)
                Button("确认启动…"){confirm=true}.buttonStyle(.borderedProminent)
                    .disabled(api.busy || !rows(api.data,"agent").contains{str($0,"id")==agent})
                DisclosureGroup("更换关联项目") {
                    Picker("项目",selection:$selected) {
                        Text("请选择").tag("")
                        ForEach(rows(api.data,"workspace"),id:\.identity){Text(str($0,"name")).tag(str($0,"id"))}
                    }
                    Button("保存关联"){api.action(["op":"attach","id":id,"workspace":selected]) {_ in baseline=""}}.disabled(selected.isEmpty || api.busy)
                }
            }
        }.onAppear {if !rows(api.data,"agent").contains(where:{str($0,"id")==agent}) {agent=str(rows(api.data,"agent").first ?? [:],"id")} }
    }
    var running:some View {
        let raw=str(task,"status")
        let key=str(task,"id")
        return Group {
            Surface {
                Text(str(env,"name")+" · 配置 v\(num(env,"version"))").font(.headline)
                LabeledContent("基线",value:str(task,"baseline"))
                LabeledContent("环境",value:modeName(str(env,"mode"))+" · 模拟")
                LabeledContent("执行者",value:str(obj(task,"agent"),"name")+" · v\(num(obj(task,"agent"),"version"))")
                LabeledContent("实验预算",value:"\(num(task,"round")) / \(num(task,"max_experiments"))")
                LabeledContent("整体 AUC 下限",value:String(env["floor"] as? Double ?? 0.715))
                DisclosureGroup("配置快照") {
                    Text("代码：\(str(env,"repo"))\n数据：\(str(env,"dataset"))\n训练：\(str(env,"train"))\n评测：\(str(env,"evaluate"))")
                        .textSelection(.enabled)
                    Text(str(obj(task,"agent"),"instructions")).textSelection(.enabled)
                }
            }
            Surface {
                Text("正在运行").font(.headline)
                if currentJob.isEmpty { Text("当前没有训练 Job。").foregroundStyle(.secondary) }
                else {
                    Text("Job \(str(currentJob,"id"))").font(.caption.monospaced()).textSelection(.enabled)
                    Text(currentJob["result"] == nil ? "训练中或等待结果 · 模拟" : "结果已返回，等待分析")
                    Text("平滑强度 \(currentJob["strength"] as? Double ?? 0,format:.number)")
                }
                if raw != "completed" {
                    HStack {
                        if raw=="paused" { Button("恢复"){api.action(["op":"resume","id":id])} }
                        else { Button("暂停后续调度"){api.action(["op":"pause","id":id])} }
                        Button("给 Worker 反馈"){feedbackOpen=true}
                    }.disabled(api.busy)
                }
            }
            Surface {
                Text("接下来").font(.headline)
                if raw=="completed" { Text("预算已用完，等待研究结论。") }
                else { Text("根据已完成结果和反馈选择下一轮。") }
                ForEach(rows(api.data,"inbox").filter{str($0,"task")==key && !["pause","resume"].contains(str($0,"message"))},id:\.identity){ row in
                    Text((row["consumed"] as? Bool == true ? str(row,"disposition","已读取")+" · " : "已送达 · ")+str(row,"message")).font(.caption)
                }
            }
            Surface {
                Text("已完成实验").font(.headline)
                let completed=rows(api.data,"experiment").filter{str($0,"task")==key}
                if completed.isEmpty { Text("还没有实验结果。").foregroundStyle(.secondary) }
                ForEach(completed.reversed(),id:\.identity){ ExperimentLine(row:$0) }
                if raw=="completed" && str(plan,"decision").isEmpty {
                    HStack {
                        Button("保留候选"){api.action(["op":"decision","id":id,"value":"保留候选"])}
                            .disabled(str(obj(task,"best"),"revision").isEmpty)
                        Button("不采用"){api.action(["op":"decision","id":id,"value":"不采用"])}
                    }
                } else if !str(plan,"decision").isEmpty { Text("结论：\(str(plan,"decision"))") }
            }
        }
    }
}

struct WorkspaceForm: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var api:Client
    let row:Record
    let attachPlan:String
    let save:(Record)->Void
    @State private var fields:[String:String]=[:]
    @State private var mode="local"
    @State private var floor="0.715"
    @State private var check=""
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            Text(str(row,"id").isEmpty ? "初始化研究项目" : "编辑项目配置").font(.title2.bold())
            Text("配置会随计划启动锁定。当前版本只运行模拟实验，不会访问填写的仓库、命令或远端连接。")
                .foregroundStyle(.secondary)
            ScrollView {
                Form {
                    field("项目名称","name"); field("代码地址","repo"); field("默认基线","baseline"); field("数据版本","dataset")
                    field("训练入口","train"); field("评测入口","evaluate")
                    TextField("整体 AUC 下限",text:$floor)
                    Picker("执行环境",selection:$mode){ ForEach(modes,id:\.0){Text($0.1).tag($0.0)} }
                    if mode=="hybrid" {field("远端训练连接","training_host");field("代码交付方式","delivery")}
                    if mode=="remote" {field("远端 Agent 连接","agent_host");field("远端工作目录","remote_dir")}
                }.formStyle(.grouped)
            }
            if !api.error.isEmpty { Text(api.error).font(.caption).foregroundStyle(.red) }
            else if !check.isEmpty { Text(check).font(.caption).foregroundStyle(.secondary) }
            HStack {
                Button("取消",role:.cancel){api.error="";dismiss()}; Spacer()
                Button("检查配置"){api.action(payload("check")){check=str($0,"message")}}
                Button("保存项目"){api.action(payload("workspace"),then:save)}.buttonStyle(.borderedProminent)
            }.disabled(api.busy)
        }.padding(22).frame(width:540,height:540)
            .onAppear {
                for (key,value) in row {fields[key]=value as? String}
                mode=str(row,"mode","local");floor=String(row["floor"] as? Double ?? 0.715)
            }
    }
    func field(_ title:String,_ key:String)->some View {
        TextField(title,text:Binding(get:{fields[key] ?? ""},set:{fields[key]=$0;check=""}))
    }
    func payload(_ op:String)->Record {
        var data=fields as Record
        data["op"]=op;data["mode"]=mode;data["floor"]=Double(floor) ?? -1;data["id"]=str(row,"id")
        if op=="workspace" && !attachPlan.isEmpty { data["attach_plan"]=attachPlan }
        return data
    }
}
struct PlanForm: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var api:Client
    let projectID:String
    let thread:Record
    let save:(Record)->Void
    @State private var title=""
    @State private var direction=""
    @State private var project=""
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            Text("新建研究计划").font(.title2.bold())
            Text("先记录要验证的问题。项目可在启动实验前再关联。").foregroundStyle(.secondary)
            TextField("标题",text:$title)
            TextField("大致研究方向",text:$direction,axis:.vertical).lineLimit(3...7)
            Picker("所属项目",selection:$project){
                Text("暂不关联").tag("")
                ForEach(rows(api.data,"workspace"),id:\.identity){Text(str($0,"name")).tag(str($0,"id"))}
            }
            if !api.error.isEmpty { Text(api.error).font(.caption).foregroundStyle(.red) }
            HStack {Button("取消",role:.cancel){api.error="";dismiss()}; Spacer()
                Button("创建并打开"){api.action(["op":"plan","title":title,"direction":direction,"workspace":project,"source":str(thread,"id")],then:save)}
                    .buttonStyle(.borderedProminent).disabled(title.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || direction.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || api.busy)
            }
        }.textFieldStyle(.roundedBorder).padding(22).frame(width:475)
        .onAppear {
            project=projectID
            if !thread.isEmpty {
                title=str(thread,"title")
                direction=rows(thread,"messages").filter{str($0,"role")=="user"}.map{str($0,"text")}.joined(separator:"\n")
            }
        }
    }
}
struct AgentForm: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var api:Client
    let row:Record
    let save:(Record)->Void
    @State private var name=""
    @State private var instructions=""
    @State private var wide=false
    var body:some View {
        VStack(alignment:.leading,spacing:13) {
            Text(row.isEmpty ? "新建智能体" : "保存智能体新版本").font(.title2.bold())
            LabeledContent("运行时",value:"本机进程 · Mock Worker")
            TextField("名称",text:$name)
            TextField("工作指令 · Markdown",text:$instructions,axis:.vertical).lineLimit(4...8)
            Text("已启用：adaptive-ctr").font(.caption)
            Toggle("启用 wide-search",isOn:$wide)
            if !api.error.isEmpty { Text(api.error).font(.caption).foregroundStyle(.red) }
            HStack {Button("取消",role:.cancel){api.error="";dismiss()}; Spacer()
                Button("保存"){api.action(["op":"agent","id":str(row,"id"),"name":name,"instructions":instructions,
                                           "skills":wide ? ["adaptive-ctr","wide-search"] : ["adaptive-ctr"]],then:save)}
                    .buttonStyle(.borderedProminent).disabled(name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || api.busy)
            }
        }.textFieldStyle(.roundedBorder).padding(22).frame(width:460)
        .onAppear{name=str(row,"name");instructions=str(row,"instructions");wide=(row["skills"] as? [String] ?? []).contains("wide-search")}
    }
}
struct SettingsView: View {
    @ObservedObject var api:Client
    @State private var slots=2
    @State private var delay="1.5"
    @State private var saved=false
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:17) {
                Text("设置").font(.system(.largeTitle,design:.serif).bold())
                Surface {
                    Text("模拟运行").font(.headline)
                    Stepper("训练并发上限：\(slots)",value:$slots,in:1...8)
                    TextField("每轮模拟训练秒数",text:$delay).frame(maxWidth:260)
                    Button("保存设置"){api.action(["op":"settings","slots":slots,"delay":Double(delay) ?? -1]) {_ in saved=true}}.buttonStyle(.borderedProminent).disabled(api.busy)
                    if saved {Text("设置已保存。").foregroundStyle(.secondary)}
                }
            }.padding(30)
        }.onAppear {
            let row=obj(api.data,"settings");slots=num(row,"slots",2);delay=String(row["delay"] as? Double ?? 1.5)
        }
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    static let client=Client()
    func applicationWillTerminate(_ notification: Notification) { Self.client.stop() }
}
#if TRIPSCI_SMOKE
@main struct NativeSmoke {
    @MainActor static func main() async { await smoke() }
}
#else
@main struct TripSciApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        WindowGroup("TripSci",id:"main") { RootView(api:AppDelegate.client) }
            .defaultSize(width:1150,height:730)
            .commands { CommandGroup(replacing:.newItem) {} }
    }
}

#endif

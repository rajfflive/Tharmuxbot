import { Link } from "wouter";
import { useGetDashboardStats } from "@workspace/api-client-react";
import { Activity, Globe, Plus, TrendingUp, Zap, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

function StatCard({ label, value, icon: Icon, sub }: { label: string; value: number | string; icon: React.ElementType; sub?: string }) {
  return (
    <div className="bg-card border border-border rounded-lg p-5 flex items-start gap-4" data-testid={`stat-card-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="p-2.5 rounded-md bg-primary/10 text-primary shrink-0">
        <Icon size={18} />
      </div>
      <div>
        <p className="text-muted-foreground text-xs font-medium uppercase tracking-widest mb-1">{label}</p>
        <p className="text-2xl font-bold font-mono text-foreground">{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </div>
    </div>
  );
}

function statusDot(status: string) {
  if (status === "running") return "bg-emerald-500 shadow-[0_0_6px_rgba(52,211,153,0.6)]";
  if (status === "building") return "bg-amber-500 animate-pulse";
  if (status === "failed") return "bg-destructive";
  return "bg-muted-foreground";
}

export default function DashboardPage() {
  const { data: stats, isLoading } = useGetDashboardStats();

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground text-sm mt-1">Overview of your hosted API services</p>
        </div>
        <Link href="/services/new">
          <Button className="gap-2" data-testid="button-add-service">
            <Plus size={16} />
            Add Service
          </Button>
        </Link>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Total Services" value={stats?.totalServices ?? 0} icon={Globe} />
          <StatCard
            label="Running"
            value={stats?.runningServices ?? 0}
            icon={Server}
            sub={`of ${stats?.totalServices ?? 0} services`}
          />
          <StatCard label="Total Requests" value={(stats?.totalRequests ?? 0).toLocaleString()} icon={Activity} />
          <StatCard label="Added This Week" value={stats?.servicesThisWeek ?? 0} icon={TrendingUp} sub="new services" />
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Top Services</h2>
          <Link href="/services">
            <Button variant="ghost" size="sm" className="text-muted-foreground text-xs" data-testid="link-view-all-services">
              View all
            </Button>
          </Link>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-lg" />
            ))}
          </div>
        ) : stats?.topServices && stats.topServices.length > 0 ? (
          <div className="border border-border rounded-lg divide-y divide-border overflow-hidden">
            {stats.topServices.map((svc) => (
              <Link key={svc.id} href={`/services/${svc.id}`}>
                <div
                  className="flex items-center justify-between px-5 py-4 hover:bg-muted/30 transition-colors cursor-pointer"
                  data-testid={`service-row-${svc.id}`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${statusDot(svc.status)}`} />
                    <div>
                      <p className="font-medium text-sm">{svc.name}</p>
                      <p className="text-xs text-muted-foreground font-mono">/api/proxy/{svc.slug}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-xs text-muted-foreground font-mono">{svc.requestCount.toLocaleString()} reqs</span>
                    <Badge
                      className={`text-xs ${
                        svc.status === "running"
                          ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                          : svc.status === "building"
                          ? "bg-amber-500/20 text-amber-400 border-amber-500/30"
                          : svc.status === "failed"
                          ? "bg-destructive/20 text-destructive border-destructive/30"
                          : ""
                      }`}
                      variant={svc.isActive ? "default" : "secondary"}
                    >
                      {svc.status === "idle" ? (svc.isActive ? "Active" : "Inactive") : svc.status.charAt(0).toUpperCase() + svc.status.slice(1)}
                    </Badge>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="border border-dashed border-border rounded-lg p-12 text-center">
            <Globe className="mx-auto mb-3 text-muted-foreground" size={32} />
            <p className="font-medium mb-1">No services yet</p>
            <p className="text-sm text-muted-foreground mb-4">Deploy your first GitHub repo or register an external API</p>
            <Link href="/services/new">
              <Button size="sm" className="gap-2" data-testid="button-add-first-service">
                <Plus size={14} />
                Add Service
              </Button>
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

import { pgTable, text, serial, timestamp, boolean, integer } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";

export const servicesTable = pgTable("services", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  slug: text("slug").notNull().unique(),
  description: text("description"),
  targetUrl: text("target_url"),
  githubRepo: text("github_repo"),
  isActive: boolean("is_active").notNull().default(true),
  status: text("status").notNull().default("idle"),
  deployedPort: integer("deployed_port"),
  runtime: text("runtime"),
  startCommand: text("start_command"),
  buildCommand: text("build_command"),
  envVars: text("env_vars"),
  requestCount: integer("request_count").notNull().default(0),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow().$onUpdate(() => new Date()),
});

export const insertServiceSchema = createInsertSchema(servicesTable).omit({
  id: true,
  requestCount: true,
  status: true,
  deployedPort: true,
  createdAt: true,
  updatedAt: true,
});
export type InsertService = z.infer<typeof insertServiceSchema>;
export type Service = typeof servicesTable.$inferSelect;

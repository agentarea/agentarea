import { Input } from "@/components/ui/input";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Key, Settings, Link } from "lucide-react";
import { Controller, Control, FieldErrors } from "react-hook-form";
import { motion, AnimatePresence } from "framer-motion";

interface BaseInfoProps {
  control: Control<any>;
  errors: FieldErrors<any>;
  providerSpecId?: string;
}

export default function BaseInfo({ control, errors, providerSpecId }: BaseInfoProps) {
    return (
        <AnimatePresence>
            {providerSpecId && (
              <motion.div
                initial={{ 
                  height: 0, 
                  opacity: 0,
                  scale: 0.95,
                  overflow: "hidden"
                }}
                animate={{ 
                  height: "auto", 
                  opacity: 1,
                  scale: 1,
                  overflow: "visible"
                }}
                exit={{ 
                  height: 0, 
                  opacity: 0,
                  scale: 0.95,
                  overflow: "hidden"
                }}
                transition={{ 
                  duration: 0.6, 
                  ease: [0.4, 0, 0.2, 1],
                  opacity: { duration: 0.4, delay: 0.2 }
                }}
                className="space-y-6"
              >
                <motion.div 
                  className="space-y-2"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: 0.3 }}
                >
                  <FormLabel htmlFor="name" icon={Settings} required>Configuration Name</FormLabel>
                  <Controller
                    name="name"
                    control={control}
                    render={({ field }) => (
                      <Input
                        id="name"
                        type="text"
                        value={field.value}
                        onChange={field.onChange}
                        placeholder="e.g., Production OpenAI Config"
                        required
                      />
                    )}
                  />
                  {errors.name && (
                    <motion.p 
                      className="text-sm text-red-600"
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.2 }}
                    >
                      {String(errors.name.message)}
                    </motion.p>
                  )}
                </motion.div>

                <motion.div 
                  className="space-y-2"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: 0.4 }}
                >
                  <FormLabel htmlFor="api_key" required icon={Key}>API Key</FormLabel>
                  <Controller
                    name="api_key"
                    control={control}
                    render={({ field }) => (
                      <Input
                        id="api_key"
                        type="password"
                        value={field.value}
                        onChange={field.onChange}
                        placeholder="Enter your API key"
                        required
                      />
                    )}
                  />
                  {errors.api_key && (
                    <motion.p 
                      className="text-sm text-red-600"
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.2 }}
                    >
                      {String(errors.api_key.message)}
                    </motion.p>
                  )}
                </motion.div>

                <motion.div 
                  className="space-y-2"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: 0.5 }}
                >
                  <FormLabel htmlFor="endpoint_url" icon={Link} optional>Custom Endpoint URL</FormLabel>
                  <Controller
                    name="endpoint_url"
                    control={control}
                    render={({ field }) => (
                      <Input
                        id="endpoint_url"
                        type="url"
                        value={field.value || ''}
                        onChange={field.onChange}
                        placeholder="https://api.example.com/v1"
                      />
                    )}
                  />
                  {errors.endpoint_url && (
                    <motion.p 
                      className="text-sm text-red-600"
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.2 }}
                    >
                      {String(errors.endpoint_url.message)}
                    </motion.p>
                  )}
                </motion.div>
              </motion.div>
            )}
        </AnimatePresence>
    )
}